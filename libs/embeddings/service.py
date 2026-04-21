"""Embedding service — orchestrates adapter + qdrant store from config.

Loaded lazily during scan when qdrant.enabled=true. Handles:
1. Create adapter from config (openai/local/fake)
2. Connect to Qdrant, ensure collections
3. Embed changed files (summaries + symbols)
4. Search for retrieval pipeline
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from pathlib import Path
from typing import Any

from libs.core.projects_config import DaemonConfig, EmbeddingConfig, QdrantConfig
from libs.embeddings.adapter import (
    EmbeddingAdapter,
    FakeBgeM3Adapter,
    FakeEmbeddingAdapter,
    MultiVectorEmbeddingAdapter,
    OpenAIEmbeddingAdapter,
)
from libs.embeddings.qdrant_store import (
    MultiVectorItem,
    QdrantStore,
    SummarySearchHit,
    SummaryVectorItem,
)

log = logging.getLogger(__name__)


OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
# Ollama ignores the API key value but the openai SDK requires a non-empty
# string — "ollama" is the community convention.
OLLAMA_DUMMY_API_KEY = "ollama"


def _build_adapter(cfg: EmbeddingConfig) -> EmbeddingAdapter:
    if cfg.provider == "fake":
        return FakeEmbeddingAdapter(dimension=cfg.dimension)
    if cfg.provider == "fake_bge_m3":
        # Deterministic multi-vector adapter for tests that want the hybrid
        # routing path without loading the real 2.3 GB FlagEmbedding model.
        return FakeBgeM3Adapter(dimension=cfg.dimension)
    if cfg.provider == "bge_m3":
        # Lazy import — keeps the service importable when the [bge-m3] extra
        # isn't installed (e.g. the agent daemon on a fresh dev machine).
        from libs.embeddings.bge_m3 import BgeM3Adapter  # noqa: PLC0415

        return BgeM3Adapter(device=cfg.bge_m3_device)
    if cfg.provider == "openai":
        api_key = os.environ.get(cfg.api_key_env_var) if cfg.api_key_env_var else None
        kwargs: dict[str, Any] = {"model": cfg.model, "dimension": cfg.dimension}
        if api_key:
            kwargs["api_key"] = api_key
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        return OpenAIEmbeddingAdapter(**kwargs)
    if cfg.provider == "ollama":
        # Ollama exposes an OpenAI-compatible /v1/embeddings endpoint.
        # Reuse the openai adapter; auto-fill base_url and dummy key.
        return OpenAIEmbeddingAdapter(
            model=cfg.model,
            api_key=OLLAMA_DUMMY_API_KEY,
            base_url=cfg.base_url or OLLAMA_DEFAULT_BASE_URL,
            dimension=cfg.dimension,
        )
    # fallback to fake
    return FakeEmbeddingAdapter(dimension=cfg.dimension)


def _is_multi_vector(adapter: EmbeddingAdapter) -> bool:
    """Runtime check — does ``adapter`` support the hybrid retrieval protocol?"""
    return isinstance(adapter, MultiVectorEmbeddingAdapter)


def _build_store(cfg: QdrantConfig) -> QdrantStore:
    api_key = os.environ.get(cfg.api_key_env_var, "") if cfg.api_key_env_var else None
    return QdrantStore(url=cfg.url, api_key=api_key if api_key else None)


def _run_embed_once(
    *,
    config: DaemonConfig,
    project_id: str,
    files_data: list[SummaryVectorItem],
) -> int:
    adapter = _build_adapter(config.embedding)
    store = _build_store(config.qdrant)
    return asyncio.run(
        _do_embed(
            adapter=adapter,
            store=store,
            project_id=project_id,
            files_data=files_data,
            cfg=config.embedding,
        )
    )


async def _embed_and_upsert(
    *,
    adapter: EmbeddingAdapter,
    store: QdrantStore,
    project_id: str,
    files_data: list[SummaryVectorItem],
) -> int:
    """Embed file summaries and upsert to Qdrant. Returns count of points upserted."""
    if not files_data:
        return 0

    texts = [f["text"] for f in files_data]

    # Batch embed (max 100 at a time to avoid API limits)
    all_vectors: list[list[float]] = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vectors = await adapter.embed_batch(batch)
        all_vectors.extend(vectors)

    items: list[SummaryVectorItem] = []
    for fd, vec in zip(files_data, all_vectors, strict=True):
        items.append(
            {
                "vector": vec,
                "file_path": fd["file_path"],
                "content_hash": fd.get("content_hash", ""),
                "language": fd.get("language", ""),
                "entity_type": fd.get("entity_type", "file"),
            }
        )

    # Batch upsert (max 100 points at a time to avoid Qdrant timeouts)
    upsert_batch = 100
    for i in range(0, len(items), upsert_batch):
        item_batch = items[i : i + upsert_batch]
        await store.upsert_summaries(project_id=project_id, items=item_batch)

    return len(items)


def embed_project_files(
    *,
    config: DaemonConfig,
    project_root: Path,
    project_slug: str,
    changed_files: list[dict[str, Any]],
) -> int:
    """Synchronous entry point for scan pipeline. Embeds changed files.

    Each dict in changed_files should have: file_path, content, content_hash, language.
    Returns number of points upserted, or 0 if qdrant disabled.
    """
    if not config.qdrant.enabled:
        return 0

    if not changed_files:
        return 0

    # Prepare texts: use first 2000 chars of each file as summary embedding
    files_data: list[SummaryVectorItem] = []
    for f in changed_files:
        content = f.get("content", "")
        # Truncate to ~2000 chars for embedding (covers most functions/classes)
        text = content[:2000] if content else f["file_path"]
        files_data.append(
            {
                "file_path": f["file_path"],
                "text": text,
                "content_hash": f.get("content_hash", ""),
                "language": f.get("language", ""),
                "entity_type": "file",
            }
        )

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            count = _run_embed_once(
                config=config,
                project_id=project_slug,
                files_data=files_data,
            )
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                count = executor.submit(
                    _run_embed_once,
                    config=config,
                    project_id=project_slug,
                    files_data=files_data,
                ).result()
        log.info("embedded %d files for %s", count, project_slug)
        return count
    except Exception:
        log.warning(
            "embedding failed for %s, continuing without vector index",
            project_slug,
            exc_info=True,
        )
        return 0


async def _embed_and_upsert_multi(  # noqa: PLR0913 — four collaborators + two toggles
    *,
    adapter: MultiVectorEmbeddingAdapter,
    store: QdrantStore,
    project_id: str,
    files_data: list[SummaryVectorItem],
    use_sparse: bool,
    use_colbert: bool,
) -> int:
    """Embed file summaries with dense + sparse + colbert and upsert via hybrid path."""
    if not files_data:
        return 0

    texts = [f["text"] for f in files_data]

    dense_all: list[list[float]] = []
    sparse_all: list[Any] = []
    colbert_all: list[list[list[float]]] = []

    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        multi = await adapter.embed_batch_multi(
            batch,
            dense=True,
            sparse=use_sparse,
            colbert=use_colbert,
        )
        assert multi.dense is not None  # dense is always requested
        dense_all.extend(multi.dense)
        if multi.sparse is not None:
            sparse_all.extend(multi.sparse)
        if multi.colbert is not None:
            colbert_all.extend(multi.colbert)

    items: list[MultiVectorItem] = []
    for idx, fd in enumerate(files_data):
        mv_item: MultiVectorItem = {
            "file_path": fd["file_path"],
            "content_hash": fd.get("content_hash", ""),
            "language": fd.get("language", ""),
            "entity_type": fd.get("entity_type", "file"),
            "dense": dense_all[idx],
        }
        if sparse_all:
            mv_item["sparse"] = sparse_all[idx]
        if colbert_all:
            mv_item["colbert"] = colbert_all[idx]
        items.append(mv_item)

    upsert_batch = 100
    for i in range(0, len(items), upsert_batch):
        await store.upsert_multi(
            collection="devctx_summaries",
            project_id=project_id,
            items=items[i : i + upsert_batch],
        )
    return len(items)


async def _do_embed(
    *,
    adapter: EmbeddingAdapter,
    store: QdrantStore,
    project_id: str,
    files_data: list[SummaryVectorItem],
    cfg: EmbeddingConfig,
) -> int:
    hybrid = _is_multi_vector(adapter)
    await store.ensure_collections(dimension=adapter.dimension, hybrid=hybrid)
    if hybrid:
        count = await _embed_and_upsert_multi(
            adapter=adapter,  # type: ignore[arg-type]
            store=store,
            project_id=project_id,
            files_data=files_data,
            use_sparse=cfg.bge_m3_use_sparse,
            use_colbert=cfg.bge_m3_use_colbert,
        )
    else:
        count = await _embed_and_upsert(
            adapter=adapter,
            store=store,
            project_id=project_id,
            files_data=files_data,
        )
    await store.close()
    return count


async def vector_search(
    *,
    config: DaemonConfig,
    query: str,
    project_id: str,
    limit: int = 20,
) -> dict[str, float]:
    """Search Qdrant for files matching query. Returns {file_path: score}.

    When the adapter supports ``MultiVectorEmbeddingAdapter`` the query runs
    through ``search_hybrid`` with Fusion.RRF; otherwise the dense-only path
    (``search_summaries``) is used. Returns empty dict on error or when
    qdrant is disabled.
    """
    if not config.qdrant.enabled:
        return {}

    adapter = _build_adapter(config.embedding)
    store = _build_store(config.qdrant)
    hybrid = _is_multi_vector(adapter)

    try:
        await store.ensure_collections(dimension=adapter.dimension, hybrid=hybrid)
        if hybrid:
            mv_adapter: MultiVectorEmbeddingAdapter = adapter  # type: ignore[assignment]
            multi = await mv_adapter.embed_batch_multi(
                [query],
                dense=True,
                sparse=config.embedding.bge_m3_use_sparse,
                colbert=config.embedding.bge_m3_use_colbert,
            )
            assert multi.dense is not None
            hits = await store.search_hybrid(
                collection="devctx_summaries",
                project_id=project_id,
                dense_query=multi.dense[0],
                sparse_query=multi.sparse[0] if multi.sparse else None,
                colbert_query=multi.colbert[0] if multi.colbert else None,
                limit=limit,
            )
        else:
            query_vec = (await adapter.embed_batch([query]))[0]
            hits = await store.search_summaries(
                vector=query_vec,
                project_id=project_id,
                limit=limit,
            )
        await store.close()
        typed_results: list[SummarySearchHit] = hits
        return {r["file_path"]: r.get("score", 0.0) for r in typed_results if r["file_path"]}
    except Exception:
        log.warning("vector search failed for %s, returning empty", project_id, exc_info=True)
        return {}
