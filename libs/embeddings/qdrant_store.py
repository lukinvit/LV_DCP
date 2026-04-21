"""Qdrant client wrapper for LV_DCP vector store.

Constitution invariant 7: fixed collections with payload isolation.
Collections: devctx_summaries, devctx_symbols, devctx_chunks, devctx_patterns.

Schema uses **named vectors** — a ``dense`` slot is always present and
backs the legacy OpenAI/Ollama path. When ``hybrid=True``, collections
also gain a ``colbert`` multivector slot (MAX_SIM) and a ``sparse``
sparse-vector slot, backing the bge-m3 hybrid retrieval path.

This layout keeps a single pool of collections for all providers — the
constitution forbids per-collection-per-provider sharding.
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    MultiVectorComparator,
    MultiVectorConfig,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from libs.embeddings.adapter import SparseVec

COLLECTIONS = (
    "devctx_summaries",
    "devctx_symbols",
    "devctx_chunks",
    "devctx_patterns",
)

_PAYLOAD_INDEXES = ("project_id", "language", "entity_type", "privacy_mode")

DENSE_VECTOR_NAME = "dense"
COLBERT_VECTOR_NAME = "colbert"
SPARSE_VECTOR_NAME = "sparse"


class SummaryVectorItem(TypedDict, total=False):
    id: str
    text: str
    vector: list[float]
    file_path: str
    content_hash: str
    language: str
    entity_type: str


class MultiVectorItem(TypedDict, total=False):
    """Input for a hybrid upsert — dense mandatory, others optional."""

    id: str
    file_path: str
    content_hash: str
    language: str
    entity_type: str
    dense: list[float]
    sparse: SparseVec
    colbert: list[list[float]]


class SummarySearchHit(TypedDict):
    file_path: str
    score: float


class QdrantStore:
    """Async Qdrant wrapper with fixed-collection, payload-isolated design."""

    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        location: str | None = None,
    ) -> None:
        self._is_local = location == ":memory:"
        if location == ":memory:":
            self._client = AsyncQdrantClient(location=":memory:", check_compatibility=False)
        elif url and url.startswith("https://"):
            # qdrant-client needs host/port/https for HTTPS URLs
            from urllib.parse import urlparse  # noqa: PLC0415

            parsed = urlparse(url)
            self._client = AsyncQdrantClient(
                host=parsed.hostname,
                port=parsed.port or 443,
                https=True,
                api_key=api_key,
                timeout=30,
                check_compatibility=False,
            )
        else:
            self._client = AsyncQdrantClient(
                url=url,
                api_key=api_key,
                timeout=30,
                check_compatibility=False,
            )

    async def ensure_collections(
        self,
        *,
        dimension: int,
        hybrid: bool = False,
    ) -> None:
        """Create the fixed 4 collections if missing.

        Named-vector layout:
          - ``dense`` (all modes) — ``VectorParams(size=dimension, COSINE)``
          - ``colbert`` (hybrid only) — multivector with MAX_SIM comparator
          - ``sparse`` (hybrid only) — sparse vector params

        Idempotent: existing collections are left untouched, even if their
        schema drifts from the requested one — the migration path in T024
        owns schema upgrades, not this method.
        """
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}

        vectors_config: dict[str, VectorParams] = {
            DENSE_VECTOR_NAME: VectorParams(size=dimension, distance=Distance.COSINE),
        }
        if hybrid:
            vectors_config[COLBERT_VECTOR_NAME] = VectorParams(
                size=dimension,
                distance=Distance.COSINE,
                multivector_config=MultiVectorConfig(
                    comparator=MultiVectorComparator.MAX_SIM,
                ),
            )

        sparse_vectors_config: dict[str, SparseVectorParams] | None = None
        if hybrid:
            sparse_vectors_config = {SPARSE_VECTOR_NAME: SparseVectorParams()}

        for name in COLLECTIONS:
            if name in existing_names:
                continue
            await self._client.create_collection(
                collection_name=name,
                vectors_config=vectors_config,
                sparse_vectors_config=sparse_vectors_config,
            )
            if not self._is_local:
                for field in _PAYLOAD_INDEXES:
                    await self._client.create_payload_index(
                        collection_name=name,
                        field_name=field,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )

    async def upsert_summaries(
        self,
        *,
        project_id: str,
        items: list[SummaryVectorItem],
    ) -> None:
        """Upsert file/module summary vectors (dense-only path)."""
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{project_id}/{item['file_path']}")),
                vector={DENSE_VECTOR_NAME: item["vector"]},
                payload={
                    "project_id": project_id,
                    "file_path": item["file_path"],
                    "content_hash": item.get("content_hash", ""),
                    "language": item.get("language", ""),
                    "entity_type": item.get("entity_type", "file"),
                },
            )
            for item in items
        ]
        if points:
            await self._client.upsert(collection_name="devctx_summaries", points=points)

    async def upsert_multi(
        self,
        *,
        collection: str,
        project_id: str,
        items: list[MultiVectorItem],
    ) -> None:
        """Upsert points carrying any of dense / sparse / colbert vectors.

        ``dense`` is mandatory per item; ``sparse`` and ``colbert`` are
        included only when present on the item so dense-only callers can
        reuse this method without paying for an empty slot.
        """
        if collection not in COLLECTIONS:
            raise ValueError(f"unknown collection: {collection!r}")

        points: list[PointStruct] = []
        for item in items:
            if "dense" not in item:
                raise ValueError("MultiVectorItem requires a 'dense' field")
            # qdrant-client PointStruct.vector accepts a dict whose value
            # union covers dense (list[float]), multivector (list[list[float]])
            # and sparse (SparseVector). Use Any to bypass dict invariance.
            vector: dict[str, Any] = {
                DENSE_VECTOR_NAME: item["dense"],
            }
            if "colbert" in item:
                vector[COLBERT_VECTOR_NAME] = item["colbert"]
            if "sparse" in item:
                sp = item["sparse"]
                vector[SPARSE_VECTOR_NAME] = SparseVector(indices=sp.indices, values=sp.values)
            points.append(
                PointStruct(
                    id=str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{project_id}/{item.get('file_path', '')}")
                    ),
                    vector=vector,
                    payload={
                        "project_id": project_id,
                        "file_path": item.get("file_path", ""),
                        "content_hash": item.get("content_hash", ""),
                        "language": item.get("language", ""),
                        "entity_type": item.get("entity_type", "file"),
                    },
                )
            )
        if points:
            await self._client.upsert(collection_name=collection, points=points)

    async def search_summaries(
        self,
        *,
        vector: list[float],
        project_id: str,
        limit: int = 10,
    ) -> list[SummarySearchHit]:
        """Search summary vectors filtered by project_id (dense-only path)."""
        results = await self._client.query_points(
            collection_name="devctx_summaries",
            query=vector,
            using=DENSE_VECTOR_NAME,
            query_filter=Filter(
                must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
            ),
            limit=limit,
        )
        return [
            {
                "file_path": point.payload.get("file_path", "") if point.payload else "",
                "score": point.score if hasattr(point, "score") else 0.0,
            }
            for point in results.points
        ]

    async def search_hybrid(  # noqa: PLR0913 — spec requires three query kinds + tuning knobs
        self,
        *,
        collection: str,
        project_id: str,
        dense_query: list[float] | None = None,
        sparse_query: SparseVec | None = None,
        colbert_query: list[list[float]] | None = None,
        limit: int = 10,
        prefetch_limit: int = 20,
    ) -> list[SummarySearchHit]:
        """Hybrid search via ``query_points`` with reciprocal rank fusion.

        Each non-``None`` query kind becomes a ``Prefetch`` stage; final
        ranking is ``Fusion.RRF`` across the stages. ``project_id`` filter
        is applied at the outer query level — payload-level isolation per
        constitution invariant 7.

        Dense-only callers can pass ``dense_query`` alone; this degenerates
        to a standard KNN query but keeps a single code path.
        """
        if collection not in COLLECTIONS:
            raise ValueError(f"unknown collection: {collection!r}")
        if dense_query is None and sparse_query is None and colbert_query is None:
            raise ValueError("at least one of dense/sparse/colbert queries is required")

        project_filter = Filter(
            must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
        )

        prefetches: list[Prefetch] = []
        if dense_query is not None:
            prefetches.append(
                Prefetch(
                    query=dense_query,
                    using=DENSE_VECTOR_NAME,
                    filter=project_filter,
                    limit=prefetch_limit,
                )
            )
        if sparse_query is not None:
            prefetches.append(
                Prefetch(
                    query=SparseVector(indices=sparse_query.indices, values=sparse_query.values),
                    using=SPARSE_VECTOR_NAME,
                    filter=project_filter,
                    limit=prefetch_limit,
                )
            )
        if colbert_query is not None:
            prefetches.append(
                Prefetch(
                    query=colbert_query,
                    using=COLBERT_VECTOR_NAME,
                    filter=project_filter,
                    limit=prefetch_limit,
                )
            )

        results = await self._client.query_points(
            collection_name=collection,
            prefetch=prefetches,
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=project_filter,
            limit=limit,
        )
        return [
            {
                "file_path": (point.payload or {}).get("file_path", ""),
                "score": point.score if hasattr(point, "score") else 0.0,
            }
            for point in results.points
        ]

    async def delete_by_project(self, project_id: str) -> None:
        """Delete all points for a project across all collections."""
        for name in COLLECTIONS:
            await self._client.delete(
                collection_name=name,
                points_selector=Filter(
                    must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
                ),
            )

    async def close(self) -> None:
        await self._client.close()
