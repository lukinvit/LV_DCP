"""Integration test for hybrid retrieval on rare-identifier corpus (T012).

Loads ``tests/eval/datasets/rare_symbols.yaml`` and builds a synthetic
corpus made of one target per query (carrying the rare token) plus a
pile of generic distractors. The corpus is indexed into an in-memory
Qdrant collection via :class:`FakeBgeM3Adapter` (dense + sparse; colbert
is intentionally disabled — the fake adapter's colbert seed depends on
token position, which this synthetic setup cannot guarantee to match
across query and document).

We then measure Recall@5 for:

- the dense-only production path (``QdrantStore.search_summaries``),
- the hybrid path (``QdrantStore.search_hybrid`` with RRF fusing dense
  and sparse stages).

Spec §T012 target: hybrid > 0.8, dense-only < 0.4.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import yaml
from libs.embeddings.adapter import FakeBgeM3Adapter
from libs.embeddings.qdrant_store import MultiVectorItem, QdrantStore

DATASET_PATH = Path(__file__).resolve().parents[2] / "eval" / "datasets" / "rare_symbols.yaml"

_DISTRACTOR_THEMES = (
    "Inventory audit flow summarises the stock count once a week.",
    "Cache eviction policy drains least recently used keys first.",
    "Routing table rebuilds on a reload signal from the control plane.",
    "Batch exporter flushes samples when the in-flight buffer fills.",
    "Observer hook records span attributes at the outbound boundary.",
    "Scheduler reschedules the task after the back-pressure window.",
    "Fallback renderer degrades layout when the theme pack is missing.",
    "Pipeline warms secondary indexes after the primary write commits.",
    "Health probe aggregates readiness across all managed processes.",
    "Snapshot uploader seals directories before handing off to storage.",
)


def _load_dataset() -> list[dict[str, str]]:
    raw = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8"))
    return cast(list[dict[str, str]], raw["queries"])


def _distractors(count: int) -> list[tuple[str, str]]:
    """Synthesise generic prose with no rare tokens from the dataset."""
    out: list[tuple[str, str]] = []
    for i in range(count):
        theme = _DISTRACTOR_THEMES[i % len(_DISTRACTOR_THEMES)]
        out.append((f"app/distractors/note_{i:03d}.md", f"{theme} Page {i}."))
    return out


@pytest.mark.asyncio
async def test_hybrid_beats_dense_only_on_rare_symbols() -> None:
    queries = _load_dataset()
    assert len(queries) >= 20, "dataset must contain the 20+ pairs spec'd in T011"

    adapter = FakeBgeM3Adapter(dimension=128)
    store = QdrantStore(location=":memory:")
    await store.ensure_collections(dimension=adapter.dimension, hybrid=True)

    corpus: list[tuple[str, str]] = [(q["target_file"], q["target_text"]) for q in queries]
    corpus.extend(_distractors(150))

    texts = [text for _, text in corpus]
    multi = await adapter.embed_batch_multi(texts, dense=True, sparse=True, colbert=False)
    assert multi.dense is not None
    assert multi.sparse is not None

    items: list[MultiVectorItem] = []
    for (path, _), dense_vec, sparse_vec in zip(corpus, multi.dense, multi.sparse, strict=True):
        items.append(
            {
                "file_path": path,
                "content_hash": "",
                "language": "synthetic",
                "entity_type": "file",
                "dense": dense_vec,
                "sparse": sparse_vec,
            }
        )
    await store.upsert_multi(collection="devctx_summaries", project_id="rare", items=items)

    hybrid_hits = 0
    dense_hits = 0
    for q in queries:
        q_multi = await adapter.embed_batch_multi(
            [q["query"]], dense=True, sparse=True, colbert=False
        )
        assert q_multi.dense is not None
        assert q_multi.sparse is not None

        hybrid = await store.search_hybrid(
            collection="devctx_summaries",
            project_id="rare",
            dense_query=q_multi.dense[0],
            sparse_query=q_multi.sparse[0],
            limit=5,
        )
        dense = await store.search_summaries(vector=q_multi.dense[0], project_id="rare", limit=5)

        target = q["target_file"]
        if any(h["file_path"] == target for h in hybrid):
            hybrid_hits += 1
        if any(h["file_path"] == target for h in dense):
            dense_hits += 1

    await store.close()

    total = len(queries)
    hybrid_recall = hybrid_hits / total
    dense_recall = dense_hits / total

    assert hybrid_recall > 0.8, f"hybrid recall@5 = {hybrid_recall:.3f} is below the 0.8 US1 target"
    assert dense_recall < 0.4, (
        f"dense-only recall@5 = {dense_recall:.3f} — FakeBgeM3Adapter dense is "
        "hash-random so rare-identifier recall should stay under 0.4; if this "
        "spikes the test corpus has leaked a signal into the dense path"
    )
    assert hybrid_recall - dense_recall > 0.4, (
        f"hybrid must dominate dense-only by > 0.4 on rare tokens "
        f"(got hybrid={hybrid_recall:.3f}, dense={dense_recall:.3f})"
    )
