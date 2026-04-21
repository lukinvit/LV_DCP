"""Tests for Qdrant store wrapper.

Uses the in-memory Qdrant client (no server needed).
"""

import pytest
from libs.embeddings.adapter import FakeBgeM3Adapter, FakeEmbeddingAdapter, SparseVec
from libs.embeddings.qdrant_store import (
    COLBERT_VECTOR_NAME,
    COLLECTIONS,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    QdrantStore,
)


@pytest.fixture
def store() -> QdrantStore:
    return QdrantStore(location=":memory:")


@pytest.fixture
def adapter() -> FakeEmbeddingAdapter:
    return FakeEmbeddingAdapter(dimension=64)


@pytest.mark.asyncio
async def test_ensure_collections_creates_all(
    store: QdrantStore, adapter: FakeEmbeddingAdapter
) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    client = store._client
    collections = await client.get_collections()
    names = {c.name for c in collections.collections}
    for coll_name in COLLECTIONS:
        assert coll_name in names


@pytest.mark.asyncio
async def test_upsert_and_search(store: QdrantStore, adapter: FakeEmbeddingAdapter) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    vectors = await adapter.embed_batch(["test function for user auth"])
    await store.upsert_summaries(
        project_id="proj1",
        items=[
            {
                "id": "file1",
                "vector": vectors[0],
                "file_path": "src/auth.py",
                "content_hash": "abc123",
                "language": "python",
                "entity_type": "file",
            }
        ],
    )
    query_vec = (await adapter.embed_batch(["user authentication"]))[0]
    results = await store.search_summaries(
        vector=query_vec,
        project_id="proj1",
        limit=5,
    )
    assert len(results) >= 1
    assert results[0]["file_path"] == "src/auth.py"


@pytest.mark.asyncio
async def test_delete_by_project(store: QdrantStore, adapter: FakeEmbeddingAdapter) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    vectors = await adapter.embed_batch(["test"])
    await store.upsert_summaries(
        project_id="proj1",
        items=[
            {
                "id": "f1",
                "vector": vectors[0],
                "file_path": "a.py",
                "content_hash": "h1",
                "language": "python",
                "entity_type": "file",
            }
        ],
    )
    await store.delete_by_project("proj1")
    query_vec = (await adapter.embed_batch(["test"]))[0]
    results = await store.search_summaries(vector=query_vec, project_id="proj1", limit=5)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_ensure_collections_idempotent(
    store: QdrantStore, adapter: FakeEmbeddingAdapter
) -> None:
    await store.ensure_collections(dimension=adapter.dimension)
    await store.ensure_collections(dimension=adapter.dimension)
    collections = await store._client.get_collections()
    names = [c.name for c in collections.collections]
    # No duplicates
    assert len(names) == len(set(names))


# --- T008: hybrid schema + upsert_multi ---------------------------------


@pytest.mark.asyncio
async def test_ensure_collections_hybrid_has_three_vector_slots(
    store: QdrantStore,
) -> None:
    """hybrid=True → dense + colbert (multivector) + sparse slots present."""
    await store.ensure_collections(dimension=32, hybrid=True)
    info = await store._client.get_collection("devctx_summaries")
    vectors_cfg = info.config.params.vectors
    # Named vectors for dense + colbert
    assert DENSE_VECTOR_NAME in vectors_cfg
    assert COLBERT_VECTOR_NAME in vectors_cfg
    # colbert must declare multivector_config
    assert vectors_cfg[COLBERT_VECTOR_NAME].multivector_config is not None
    # sparse lives under a sibling config
    sparse_cfg = info.config.params.sparse_vectors
    assert sparse_cfg is not None
    assert SPARSE_VECTOR_NAME in sparse_cfg


@pytest.mark.asyncio
async def test_ensure_collections_dense_only_has_no_sparse(
    store: QdrantStore,
) -> None:
    """hybrid=False → no colbert, no sparse (backward compat)."""
    await store.ensure_collections(dimension=32)
    info = await store._client.get_collection("devctx_summaries")
    vectors_cfg = info.config.params.vectors
    assert DENSE_VECTOR_NAME in vectors_cfg
    assert COLBERT_VECTOR_NAME not in vectors_cfg
    assert not info.config.params.sparse_vectors


@pytest.mark.asyncio
async def test_upsert_multi_dense_sparse_colbert_roundtrip(
    store: QdrantStore,
) -> None:
    adapter = FakeBgeM3Adapter(dimension=32)
    await store.ensure_collections(dimension=32, hybrid=True)
    multi = await adapter.embed_batch_multi(["alpha beta"])

    assert multi.dense is not None
    assert multi.sparse is not None
    assert multi.colbert is not None
    from libs.embeddings.qdrant_store import MultiVectorItem

    item: MultiVectorItem = {
        "file_path": "alpha.py",
        "content_hash": "h1",
        "language": "python",
        "entity_type": "file",
        "dense": multi.dense[0],
        "sparse": multi.sparse[0],
        "colbert": multi.colbert[0],
    }
    await store.upsert_multi(
        collection="devctx_summaries",
        project_id="proj1",
        items=[item],
    )

    # Dense-only retrieval still works on the hybrid collection via using=
    result = await store._client.query_points(
        collection_name="devctx_summaries",
        query=multi.dense[0],
        using=DENSE_VECTOR_NAME,
        limit=5,
    )
    assert len(result.points) == 1
    assert result.points[0].payload is not None
    assert result.points[0].payload["file_path"] == "alpha.py"


@pytest.mark.asyncio
async def test_upsert_multi_rejects_unknown_collection(store: QdrantStore) -> None:
    await store.ensure_collections(dimension=32, hybrid=True)
    with pytest.raises(ValueError, match="unknown collection"):
        await store.upsert_multi(
            collection="not_a_real_collection",
            project_id="p",
            items=[{"dense": [0.0] * 32, "file_path": "x.py"}],
        )


@pytest.mark.asyncio
async def test_upsert_multi_requires_dense(store: QdrantStore) -> None:
    await store.ensure_collections(dimension=32, hybrid=True)
    with pytest.raises(ValueError, match="dense"):
        await store.upsert_multi(
            collection="devctx_summaries",
            project_id="p",
            items=[{"file_path": "x.py", "sparse": SparseVec(indices=[1], values=[1.0])}],  # type: ignore[typeddict-item]
        )


@pytest.mark.asyncio
async def test_upsert_multi_dense_only_works_on_hybrid_collection(
    store: QdrantStore,
) -> None:
    """A dense-only provider (OpenAI/Ollama) must coexist on a hybrid schema."""
    await store.ensure_collections(dimension=32, hybrid=True)
    await store.upsert_multi(
        collection="devctx_chunks",
        project_id="p",
        items=[
            {
                "file_path": "a.py",
                "dense": [0.1] * 32,
                "entity_type": "chunk",
            },
        ],
    )


# --- T009: search_hybrid ------------------------------------------------


@pytest.mark.asyncio
async def test_search_hybrid_rejects_empty_query(store: QdrantStore) -> None:
    await store.ensure_collections(dimension=32, hybrid=True)
    with pytest.raises(ValueError, match="at least one"):
        await store.search_hybrid(
            collection="devctx_summaries",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_search_hybrid_rejects_unknown_collection(store: QdrantStore) -> None:
    await store.ensure_collections(dimension=32, hybrid=True)
    with pytest.raises(ValueError, match="unknown collection"):
        await store.search_hybrid(
            collection="not_a_collection",
            project_id="p",
            dense_query=[0.0] * 32,
        )


@pytest.mark.asyncio
async def test_search_hybrid_dense_only(store: QdrantStore) -> None:
    """Dense-only fusion path still returns ranked hits."""
    adapter = FakeBgeM3Adapter(dimension=32)
    await store.ensure_collections(dimension=32, hybrid=True)
    multi = await adapter.embed_batch_multi(["alpha", "beta", "gamma"])
    assert multi.dense is not None and multi.sparse is not None and multi.colbert is not None
    await store.upsert_multi(
        collection="devctx_summaries",
        project_id="p",
        items=[
            {
                "file_path": f"{tok}.py",
                "dense": multi.dense[i],
                "sparse": multi.sparse[i],
                "colbert": multi.colbert[i],
            }
            for i, tok in enumerate(["alpha", "beta", "gamma"])
        ],
    )
    hits = await store.search_hybrid(
        collection="devctx_summaries",
        project_id="p",
        dense_query=multi.dense[0],
        limit=3,
    )
    assert len(hits) == 3
    assert hits[0]["file_path"] == "alpha.py"


@pytest.mark.asyncio
async def test_search_hybrid_three_kinds(store: QdrantStore) -> None:
    """All three prefetch stages participate in the fusion."""
    adapter = FakeBgeM3Adapter(dimension=32)
    await store.ensure_collections(dimension=32, hybrid=True)
    multi = await adapter.embed_batch_multi(["alpha one", "beta two", "gamma three"])
    assert multi.dense is not None and multi.sparse is not None and multi.colbert is not None
    await store.upsert_multi(
        collection="devctx_summaries",
        project_id="p",
        items=[
            {
                "file_path": f"file_{i}.py",
                "dense": multi.dense[i],
                "sparse": multi.sparse[i],
                "colbert": multi.colbert[i],
            }
            for i in range(3)
        ],
    )

    q_multi = await adapter.embed_batch_multi(["alpha one"])
    assert q_multi.dense is not None and q_multi.sparse is not None and q_multi.colbert is not None
    hits = await store.search_hybrid(
        collection="devctx_summaries",
        project_id="p",
        dense_query=q_multi.dense[0],
        sparse_query=q_multi.sparse[0],
        colbert_query=q_multi.colbert[0],
        limit=3,
    )
    assert len(hits) >= 1
    assert hits[0]["file_path"] == "file_0.py"


@pytest.mark.asyncio
async def test_search_hybrid_project_isolation(store: QdrantStore) -> None:
    """Hits from other projects must not leak even under hybrid fusion."""
    adapter = FakeBgeM3Adapter(dimension=32)
    await store.ensure_collections(dimension=32, hybrid=True)
    multi = await adapter.embed_batch_multi(["alpha"])
    assert multi.dense is not None and multi.sparse is not None and multi.colbert is not None

    # Same content indexed under two projects.
    for pid in ("p1", "p2"):
        await store.upsert_multi(
            collection="devctx_summaries",
            project_id=pid,
            items=[
                {
                    "file_path": f"{pid}_file.py",
                    "dense": multi.dense[0],
                    "sparse": multi.sparse[0],
                    "colbert": multi.colbert[0],
                }
            ],
        )

    hits = await store.search_hybrid(
        collection="devctx_summaries",
        project_id="p1",
        dense_query=multi.dense[0],
        sparse_query=multi.sparse[0],
        limit=5,
    )
    assert len(hits) == 1
    assert hits[0]["file_path"] == "p1_file.py"


@pytest.mark.asyncio
async def test_search_hybrid_sparse_finds_rare_token(store: QdrantStore) -> None:
    """Hybrid > dense-only on rare-identifier lookup — core motivation (SC-001)."""
    adapter = FakeBgeM3Adapter(dimension=32)
    await store.ensure_collections(dimension=32, hybrid=True)
    corpus = ["alpha beta gamma", "delta epsilon", "fragile_token_x9f2"]
    multi = await adapter.embed_batch_multi(corpus)
    assert multi.dense is not None and multi.sparse is not None and multi.colbert is not None
    await store.upsert_multi(
        collection="devctx_symbols",
        project_id="p",
        items=[
            {
                "file_path": f"doc_{i}.py",
                "dense": multi.dense[i],
                "sparse": multi.sparse[i],
                "colbert": multi.colbert[i],
            }
            for i in range(len(corpus))
        ],
    )

    q = await adapter.embed_batch_multi(["fragile_token_x9f2"])
    assert q.dense is not None and q.sparse is not None
    hits = await store.search_hybrid(
        collection="devctx_symbols",
        project_id="p",
        dense_query=q.dense[0],
        sparse_query=q.sparse[0],
        limit=3,
    )
    assert hits[0]["file_path"] == "doc_2.py"
