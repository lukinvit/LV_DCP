"""Tests for Qdrant store wrapper.

Uses the in-memory Qdrant client (no server needed).
"""

import pytest

from libs.embeddings.adapter import FakeEmbeddingAdapter
from libs.embeddings.qdrant_store import COLLECTIONS, QdrantStore


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
