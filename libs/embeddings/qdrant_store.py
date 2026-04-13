"""Qdrant client wrapper for LV_DCP vector store.

Constitution invariant 7: fixed collections with payload isolation.
Collections: devctx_summaries, devctx_symbols, devctx_chunks, devctx_patterns.
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

COLLECTIONS = (
    "devctx_summaries",
    "devctx_symbols",
    "devctx_chunks",
    "devctx_patterns",
)

_PAYLOAD_INDEXES = ("project_id", "language", "entity_type", "privacy_mode")


class SummaryVectorItem(TypedDict, total=False):
    id: str
    text: str
    vector: list[float]
    file_path: str
    content_hash: str
    language: str
    entity_type: str


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

    async def ensure_collections(self, *, dimension: int) -> None:
        """Create all 4 collections if they don't exist, with payload indexes."""
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}
        for name in COLLECTIONS:
            if name not in existing_names:
                await self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
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
        """Upsert file/module summary vectors."""
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{project_id}/{item['file_path']}")),
                vector=item["vector"],
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

    async def search_summaries(
        self,
        *,
        vector: list[float],
        project_id: str,
        limit: int = 10,
    ) -> list[SummarySearchHit]:
        """Search summary vectors filtered by project_id."""
        results = await self._client.query_points(
            collection_name="devctx_summaries",
            query=vector,
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
