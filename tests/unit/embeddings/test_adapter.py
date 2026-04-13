"""Tests for embedding adapters."""

from __future__ import annotations

import math

import pytest
from libs.embeddings.adapter import EmbeddingAdapter, FakeEmbeddingAdapter


@pytest.mark.asyncio
async def test_fake_adapter_dimension() -> None:
    adapter = FakeEmbeddingAdapter(dimension=128)
    result = await adapter.embed_batch(["hello world"])
    assert len(result) == 1
    assert len(result[0]) == 128


@pytest.mark.asyncio
async def test_fake_adapter_default_dimension() -> None:
    adapter = FakeEmbeddingAdapter()
    result = await adapter.embed_batch(["test"])
    assert len(result[0]) == 256


@pytest.mark.asyncio
async def test_fake_adapter_deterministic() -> None:
    adapter = FakeEmbeddingAdapter(dimension=64)
    a = await adapter.embed_batch(["same text"])
    b = await adapter.embed_batch(["same text"])
    assert a == b


@pytest.mark.asyncio
async def test_fake_adapter_different_input_different_output() -> None:
    adapter = FakeEmbeddingAdapter(dimension=64)
    results = await adapter.embed_batch(["alpha", "beta"])
    assert results[0] != results[1]


@pytest.mark.asyncio
async def test_fake_adapter_l2_normalized() -> None:
    adapter = FakeEmbeddingAdapter(dimension=128)
    result = await adapter.embed_batch(["normalize me"])
    vec = result[0]
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-6


def test_fake_adapter_model_name() -> None:
    adapter = FakeEmbeddingAdapter()
    assert adapter.model_name == "fake"


def test_protocol_compliance() -> None:
    """FakeEmbeddingAdapter satisfies the EmbeddingAdapter protocol."""
    adapter = FakeEmbeddingAdapter()
    assert isinstance(adapter, EmbeddingAdapter)


@pytest.mark.asyncio
async def test_fake_adapter_batch_size() -> None:
    adapter = FakeEmbeddingAdapter(dimension=32)
    texts = [f"text_{i}" for i in range(10)]
    results = await adapter.embed_batch(texts)
    assert len(results) == 10
    assert all(len(v) == 32 for v in results)
