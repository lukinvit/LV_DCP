"""Tests for FakeBgeM3Adapter (spec #1 T005)."""

from __future__ import annotations

import math

import pytest
from libs.embeddings.adapter import (
    BatchMultiVectorResult,
    EmbeddingAdapter,
    FakeBgeM3Adapter,
    MultiVectorEmbeddingAdapter,
    SparseVec,
)


def test_fake_bge_m3_satisfies_both_protocols() -> None:
    adapter = FakeBgeM3Adapter()
    assert isinstance(adapter, EmbeddingAdapter)
    assert isinstance(adapter, MultiVectorEmbeddingAdapter)


def test_fake_bge_m3_default_dimension() -> None:
    adapter = FakeBgeM3Adapter()
    assert adapter.dimension == 1024
    assert adapter.model_name == "fake-bge-m3"


@pytest.mark.asyncio
async def test_embed_batch_returns_dense_only() -> None:
    adapter = FakeBgeM3Adapter(dimension=64)
    vectors = await adapter.embed_batch(["alpha beta", "gamma"])
    assert len(vectors) == 2
    assert all(len(v) == 64 for v in vectors)
    for v in vectors:
        norm = math.sqrt(sum(x * x for x in v))
        assert math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6)


@pytest.mark.asyncio
async def test_embed_batch_multi_all_kinds() -> None:
    adapter = FakeBgeM3Adapter(dimension=64)
    result = await adapter.embed_batch_multi(["alpha beta gamma"])
    assert isinstance(result, BatchMultiVectorResult)
    assert result.dense is not None and len(result.dense) == 1
    assert len(result.dense[0]) == 64
    assert result.sparse is not None and len(result.sparse) == 1
    assert isinstance(result.sparse[0], SparseVec)
    assert len(result.sparse[0].indices) == len(result.sparse[0].values)
    assert len(result.sparse[0].indices) == 3  # three tokens
    assert result.colbert is not None and len(result.colbert) == 1
    assert len(result.colbert[0]) == 3  # one token-vector per input token
    assert all(len(v) == 64 for v in result.colbert[0])


@pytest.mark.asyncio
async def test_embed_batch_multi_opt_outs() -> None:
    adapter = FakeBgeM3Adapter(dimension=32)
    result = await adapter.embed_batch_multi(["alpha"], dense=True, sparse=False, colbert=False)
    assert result.dense is not None
    assert result.sparse is None
    assert result.colbert is None


@pytest.mark.asyncio
async def test_embed_batch_multi_deterministic() -> None:
    adapter = FakeBgeM3Adapter(dimension=32)
    a = await adapter.embed_batch_multi(["the quick brown fox"])
    b = await adapter.embed_batch_multi(["the quick brown fox"])
    assert a.dense == b.dense
    assert a.sparse is not None and b.sparse is not None
    assert a.sparse[0].indices == b.sparse[0].indices
    assert a.sparse[0].values == b.sparse[0].values
    assert a.colbert == b.colbert


@pytest.mark.asyncio
async def test_embed_batch_multi_empty_text_yields_single_token_colbert() -> None:
    """Edge case from spec: ``embed_batch_multi`` must not crash on empty text."""
    adapter = FakeBgeM3Adapter(dimension=16)
    result = await adapter.embed_batch_multi([""])
    assert result.sparse is not None
    assert result.sparse[0].indices == []  # no tokens -> empty sparse
    assert result.colbert is not None
    assert len(result.colbert[0]) == 1  # fallback to single "" token


def test_bge_m3_fake_adapter_fixture(
    bge_m3_fake_adapter: FakeBgeM3Adapter,
) -> None:
    """The conftest fixture is wired + returns the default shape."""
    assert isinstance(bge_m3_fake_adapter, FakeBgeM3Adapter)
    assert bge_m3_fake_adapter.dimension == 1024
