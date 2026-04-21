"""BGE-M3 multi-vector embedding adapter (dense + sparse + colbert).

One forward pass through ``BGEM3FlagModel`` emits all three representations,
which keeps GPU memory + scheduling cost aligned with the spec's SC-005 budget
(no more than 1.8x a dense-only baseline).

Heavy dependencies (``FlagEmbedding``, ``torch``, ``transformers``) live in
the ``[bge-m3]`` optional extra; the module imports them lazily so the rest
of the codebase (including tests for other providers) can load without them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from libs.embeddings.adapter import BatchMultiVectorResult, SparseVec


def _detect_device() -> str:
    """Pick the best available device: MPS → CUDA → CPU.

    Falls back to CPU if ``torch`` is not importable (e.g. the ``[bge-m3]``
    extras are not installed in the current environment).
    """
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return "cpu"

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _lex_to_sparse(weights: dict[Any, float]) -> SparseVec:
    """Convert FlagEmbedding ``lexical_weights`` mapping into ``SparseVec``.

    FlagEmbedding returns ``dict[int | str, float]`` across versions — both
    are accepted. Indices are sorted ascending for Qdrant wire stability.
    """
    items = sorted(
        ((int(k), float(v)) for k, v in weights.items()),
        key=lambda kv: kv[0],
    )
    return SparseVec(
        indices=[i for i, _ in items],
        values=[v for _, v in items],
    )


class BgeM3Adapter:
    """BGE-M3 multi-vector embedding adapter.

    Wraps ``FlagEmbedding.BGEM3FlagModel``. The forward pass is CPU/GPU-bound
    and offloaded via ``asyncio.to_thread`` so it never blocks the event loop.

    Model weights (~2.3 GB) are downloaded from Hugging Face on first use;
    set ``HF_HOME`` to control the cache location (see ADR-001 on budgets).
    """

    _DIMENSION = 1024
    _MODEL_ID = "BAAI/bge-m3"

    def __init__(
        self,
        *,
        device: str = "auto",
        use_fp16: bool = True,
        max_length: int = 8192,
        batch_size: int = 12,
    ) -> None:
        # Lazy — keeps the module loadable without the [bge-m3] extra.
        from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415

        resolved = _detect_device() if device == "auto" else device
        # fp16 on CPU is slower than fp32 — auto-disable to avoid a footgun.
        effective_fp16 = use_fp16 and resolved != "cpu"

        self._device = resolved
        self._max_length = max_length
        self._batch_size = batch_size
        self._model = BGEM3FlagModel(
            self._MODEL_ID,
            use_fp16=effective_fp16,
            device=resolved,
        )

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    @property
    def model_name(self) -> str:
        return "bge-m3"

    @property
    def device(self) -> str:
        return self._device

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        result = await self.embed_batch_multi(texts, dense=True, sparse=False, colbert=False)
        if result.dense is None:
            return []
        return result.dense

    async def embed_batch_multi(
        self,
        texts: Sequence[str],
        *,
        dense: bool = True,
        sparse: bool = True,
        colbert: bool = True,
    ) -> BatchMultiVectorResult:
        if not texts:
            return BatchMultiVectorResult(dense=None, sparse=None, colbert=None)

        raw = await asyncio.to_thread(
            self._encode_sync,
            list(texts),
            dense,
            sparse,
            colbert,
        )

        dense_out: list[list[float]] | None = None
        sparse_out: list[SparseVec] | None = None
        colbert_out: list[list[list[float]]] | None = None

        if dense and raw.get("dense_vecs") is not None:
            dense_out = [[float(x) for x in v] for v in raw["dense_vecs"]]
        if sparse and raw.get("lexical_weights") is not None:
            sparse_out = [_lex_to_sparse(w) for w in raw["lexical_weights"]]
        if colbert and raw.get("colbert_vecs") is not None:
            colbert_out = [
                [[float(x) for x in tok_vec] for tok_vec in mat] for mat in raw["colbert_vecs"]
            ]

        return BatchMultiVectorResult(
            dense=dense_out,
            sparse=sparse_out,
            colbert=colbert_out,
        )

    def _encode_sync(
        self,
        texts: list[str],
        dense: bool,
        sparse: bool,
        colbert: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = self._model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=self._max_length,
            return_dense=dense,
            return_sparse=sparse,
            return_colbert_vecs=colbert,
        )
        return out
