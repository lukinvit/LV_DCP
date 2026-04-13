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
    FakeEmbeddingAdapter,
    OpenAIEmbeddingAdapter,
)
from libs.embeddings.qdrant_store import QdrantStore, SummarySearchHit, SummaryVectorItem

log = logging.getLogger(__name__)


def _build_adapter(cfg: EmbeddingConfig) -> EmbeddingAdapter:
    if cfg.provider == "fake":
        return FakeEmbeddingAdapter(dimension=cfg.dimension)
    if cfg.provider == "openai":
        api_key = os.environ.get(cfg.api_key_env_var) if cfg.api_key_env_var else None
        kwargs: dict[str, Any] = {"model": cfg.model}
        if api_key:
            kwargs["api_key"] = api_key
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        return OpenAIEmbeddingAdapter(**kwargs)
    # fallback to fake
    return FakeEmbeddingAdapter(dimension=cfg.dimension)


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
        _do_embed(adapter=adapter, store=store, project_id=project_id, files_data=files_data)
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
        items.append({
            "vector": vec,
            "file_path": fd["file_path"],
            "content_hash": fd.get("content_hash", ""),
            "language": fd.get("language", ""),
            "entity_type": fd.get("entity_type", "file"),
        })

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
        files_data.append({
            "file_path": f["file_path"],
            "text": text,
            "content_hash": f.get("content_hash", ""),
            "language": f.get("language", ""),
            "entity_type": "file",
        })

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


async def _do_embed(
    *,
    adapter: EmbeddingAdapter,
    store: QdrantStore,
    project_id: str,
    files_data: list[SummaryVectorItem],
) -> int:
    await store.ensure_collections(dimension=adapter.dimension)
    count = await _embed_and_upsert(
        adapter=adapter, store=store, project_id=project_id, files_data=files_data,
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

    Returns empty dict if qdrant disabled or unavailable.
    """
    if not config.qdrant.enabled:
        return {}

    adapter = _build_adapter(config.embedding)
    store = _build_store(config.qdrant)

    try:
        await store.ensure_collections(dimension=adapter.dimension)
        query_vec = (await adapter.embed_batch([query]))[0]
        results = await store.search_summaries(
            vector=query_vec, project_id=project_id, limit=limit,
        )
        await store.close()
        typed_results: list[SummarySearchHit] = results
        return {r["file_path"]: r.get("score", 0.0) for r in typed_results if r["file_path"]}
    except Exception:
        log.warning("vector search failed for %s, returning empty", project_id, exc_info=True)
        return {}
