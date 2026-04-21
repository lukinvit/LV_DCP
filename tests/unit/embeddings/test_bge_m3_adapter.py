"""Tests for BgeM3Adapter (spec #1 T007).

The real FlagEmbedding + torch stack is ~2.3 GB and not installed in CI by
default. We stub ``FlagEmbedding.BGEM3FlagModel`` via ``sys.modules`` so the
adapter's wiring — device resolution, fp16 toggling, flag forwarding,
post-processing of raw outputs — can be tested in isolation.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_flag_model(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Insert a stub ``FlagEmbedding`` module and return its model mock."""
    model = MagicMock()
    model.encode.return_value = {
        "dense_vecs": [[0.1] * 1024, [0.2] * 1024],
        "lexical_weights": [{100: 0.5, 200: 0.3}, {101: 0.7}],
        "colbert_vecs": [
            [[0.01] * 1024, [0.02] * 1024],  # 2 token-vectors
            [[0.03] * 1024],  # 1 token-vector
        ],
    }
    module = MagicMock()
    module.BGEM3FlagModel = MagicMock(return_value=model)
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)
    return model


def test_bge_m3_satisfies_both_protocols(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.adapter import EmbeddingAdapter, MultiVectorEmbeddingAdapter
    from libs.embeddings.bge_m3 import BgeM3Adapter

    adapter = BgeM3Adapter(device="cpu")
    assert isinstance(adapter, EmbeddingAdapter)
    assert isinstance(adapter, MultiVectorEmbeddingAdapter)


def test_bge_m3_properties(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.bge_m3 import BgeM3Adapter

    adapter = BgeM3Adapter(device="cpu")
    assert adapter.dimension == 1024
    assert adapter.model_name == "bge-m3"
    assert adapter.device == "cpu"


def test_bge_m3_auto_disables_fp16_on_cpu(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.bge_m3 import BgeM3Adapter

    _ = BgeM3Adapter(device="cpu", use_fp16=True)
    constructor = sys.modules["FlagEmbedding"].BGEM3FlagModel
    assert constructor.call_args.kwargs["use_fp16"] is False


def test_bge_m3_keeps_fp16_on_gpu(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.bge_m3 import BgeM3Adapter

    _ = BgeM3Adapter(device="cuda", use_fp16=True)
    constructor = sys.modules["FlagEmbedding"].BGEM3FlagModel
    assert constructor.call_args.kwargs["use_fp16"] is True


@pytest.mark.asyncio
async def test_embed_batch_returns_dense_only(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.bge_m3 import BgeM3Adapter

    adapter = BgeM3Adapter(device="cpu")
    vecs = await adapter.embed_batch(["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1024
    kwargs = stub_flag_model.encode.call_args.kwargs
    assert kwargs["return_dense"] is True
    assert kwargs["return_sparse"] is False
    assert kwargs["return_colbert_vecs"] is False


@pytest.mark.asyncio
async def test_embed_batch_multi_all_kinds(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.adapter import BatchMultiVectorResult, SparseVec
    from libs.embeddings.bge_m3 import BgeM3Adapter

    adapter = BgeM3Adapter(device="cpu")
    result = await adapter.embed_batch_multi(["hello", "world"])
    assert isinstance(result, BatchMultiVectorResult)

    assert result.dense is not None
    assert len(result.dense) == 2
    assert len(result.dense[0]) == 1024

    assert result.sparse is not None
    assert len(result.sparse) == 2
    assert isinstance(result.sparse[0], SparseVec)
    assert result.sparse[0].indices == [100, 200]
    assert result.sparse[0].values == [0.5, 0.3]

    assert result.colbert is not None
    assert len(result.colbert) == 2
    assert len(result.colbert[0]) == 2
    assert len(result.colbert[1]) == 1


@pytest.mark.asyncio
async def test_embed_batch_multi_opt_outs(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.bge_m3 import BgeM3Adapter

    adapter = BgeM3Adapter(device="cpu")
    # Stub returns all three kinds unconditionally — adapter must drop the
    # opted-out ones based on kwargs.
    result = await adapter.embed_batch_multi(["x"], dense=True, sparse=False, colbert=False)
    assert result.dense is not None
    assert result.sparse is None
    assert result.colbert is None


@pytest.mark.asyncio
async def test_embed_batch_multi_empty_batch(stub_flag_model: MagicMock) -> None:
    from libs.embeddings.bge_m3 import BgeM3Adapter

    adapter = BgeM3Adapter(device="cpu")
    result = await adapter.embed_batch_multi([])
    assert result.dense is None
    assert result.sparse is None
    assert result.colbert is None
    stub_flag_model.encode.assert_not_called()


def test_lex_to_sparse_sorts_and_casts() -> None:
    from libs.embeddings.adapter import SparseVec
    from libs.embeddings.bge_m3 import _lex_to_sparse

    sp = _lex_to_sparse({5: 0.2, 1: 0.8, 3: 0.5})
    assert sp == SparseVec(indices=[1, 3, 5], values=[0.8, 0.5, 0.2])


def test_lex_to_sparse_handles_string_keys() -> None:
    from libs.embeddings.bge_m3 import _lex_to_sparse

    sp = _lex_to_sparse({"100": 0.5, "42": 0.1})
    assert sp.indices == [42, 100]
    assert sp.values == [0.1, 0.5]


def test_detect_device_falls_back_when_torch_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libs.embeddings import bge_m3

    def _raise_import_error(name: str, *args: object, **kwargs: object) -> object:
        if name == "torch":
            raise ImportError("torch not installed")
        return __import__(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _raise_import_error)
    assert bge_m3._detect_device() == "cpu"
