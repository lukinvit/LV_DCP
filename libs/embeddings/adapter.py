"""Embedding adapter protocol and implementations."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Protocol for embedding providers."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class SparseVec:
    """Sparse representation: parallel arrays of vocab indices and weights.

    Compatible with Qdrant ``SparseVector`` wire format.
    """

    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class BatchMultiVectorResult:
    """Triple output of a single bge-m3 forward pass.

    Each field has the same outer length as the input ``texts`` batch, or is
    ``None`` when the caller opted out of that vector kind.

    ``colbert[i]`` is a list of per-token vectors (variable length per text),
    shaped like ``list[token_vectors]`` where each token vector has dimension
    ``dimension``.
    """

    dense: list[list[float]] | None
    sparse: list[SparseVec] | None
    colbert: list[list[list[float]]] | None


@runtime_checkable
class MultiVectorEmbeddingAdapter(Protocol):
    """Protocol for embedders that emit dense + sparse + multivector in one pass.

    Implementations must still satisfy ``EmbeddingAdapter`` (i.e. expose
    ``embed_batch`` returning dense-only vectors) so they can act as a
    drop-in replacement when hybrid search is disabled.
    """

    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_batch_multi(
        self,
        texts: Sequence[str],
        *,
        dense: bool = True,
        sparse: bool = True,
        colbert: bool = True,
    ) -> BatchMultiVectorResult: ...


class FakeEmbeddingAdapter:
    """Deterministic embedding adapter for testing.

    Produces L2-normalized vectors derived from SHA-256 hash expansion.
    Same input always yields the same output.
    """

    def __init__(self, *, dimension: int = 256) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return "fake"

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        # Expand SHA-256 to fill requested dimension via repeated hashing.
        raw: list[float] = []
        block = 0
        while len(raw) < self._dimension:
            digest = hashlib.sha256(f"{text}:{block}".encode()).digest()
            # Each 32-byte digest gives 8 float32 values in [-1, 1].
            for i in range(0, 32, 4):
                val = struct.unpack(">I", digest[i : i + 4])[0]
                raw.append(val / 0xFFFFFFFF * 2.0 - 1.0)
            block += 1

        raw = raw[: self._dimension]

        # L2 normalize.
        norm = math.sqrt(sum(v * v for v in raw))
        if norm > 0:
            raw = [v / norm for v in raw]
        return raw


class FakeBgeM3Adapter:
    """Deterministic multi-vector adapter for tests.

    Emits hash-derived dense (1024-d by default), sparse (up to 32 non-zero
    entries), and colbert (per-whitespace-token) vectors. Same input always
    yields the same output so tests can assert against exact values.
    """

    def __init__(
        self,
        *,
        dimension: int = 1024,
        sparse_vocab_size: int = 30_000,
        sparse_top_k: int = 32,
        colbert_token_limit: int = 64,
    ) -> None:
        self._dimension = dimension
        self._sparse_vocab_size = sparse_vocab_size
        self._sparse_top_k = sparse_top_k
        self._colbert_token_limit = colbert_token_limit

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return "fake-bge-m3"

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._dense(t) for t in texts]

    async def embed_batch_multi(
        self,
        texts: Sequence[str],
        *,
        dense: bool = True,
        sparse: bool = True,
        colbert: bool = True,
    ) -> BatchMultiVectorResult:
        dense_out = [self._dense(t) for t in texts] if dense else None
        sparse_out = [self._sparse(t) for t in texts] if sparse else None
        colbert_out = [self._colbert(t) for t in texts] if colbert else None
        return BatchMultiVectorResult(dense=dense_out, sparse=sparse_out, colbert=colbert_out)

    def _dense(self, text: str) -> list[float]:
        raw: list[float] = []
        block = 0
        while len(raw) < self._dimension:
            digest = hashlib.sha256(f"{text}:dense:{block}".encode()).digest()
            for i in range(0, 32, 4):
                val = struct.unpack(">I", digest[i : i + 4])[0]
                raw.append(val / 0xFFFFFFFF * 2.0 - 1.0)
            block += 1
        raw = raw[: self._dimension]
        norm = math.sqrt(sum(v * v for v in raw))
        if norm > 0:
            raw = [v / norm for v in raw]
        return raw

    def _sparse(self, text: str) -> SparseVec:
        # Hash each whitespace token into the vocab range; accumulate
        # simple term-frequency-style weights. Deterministic.
        counts: dict[int, float] = {}
        for tok in text.split():
            h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4], "big")
            idx = h % self._sparse_vocab_size
            counts[idx] = counts.get(idx, 0.0) + 1.0
        # Keep top-k by weight for stability.
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ranked = ranked[: self._sparse_top_k]
        ranked.sort(key=lambda kv: kv[0])
        return SparseVec(
            indices=[idx for idx, _ in ranked],
            values=[val for _, val in ranked],
        )

    def _colbert(self, text: str) -> list[list[float]]:
        tokens = text.split()[: self._colbert_token_limit] or [""]
        out: list[list[float]] = []
        for t_idx, tok in enumerate(tokens):
            vec: list[float] = []
            block = 0
            while len(vec) < self._dimension:
                seed = f"{tok}:cb:{t_idx}:{block}"
                digest = hashlib.sha256(seed.encode()).digest()
                for i in range(0, 32, 4):
                    val = struct.unpack(">I", digest[i : i + 4])[0]
                    vec.append(val / 0xFFFFFFFF * 2.0 - 1.0)
                block += 1
            vec = vec[: self._dimension]
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            out.append(vec)
        return out


class OpenAIEmbeddingAdapter:
    """Wraps ``openai.AsyncOpenAI`` for embedding APIs.

    Works against any OpenAI-compatible endpoint — including Ollama's
    ``/v1/embeddings`` (supply ``base_url`` and a non-empty dummy key)
    and self-hosted gateways. The ``openai`` package is imported lazily
    so the module can be loaded without it installed.

    ``dimension`` must match the model: text-embedding-3-small → 1536,
    nomic-embed-text → 768, mxbai-embed-large → 1024, all-minilm → 384.
    Mismatch breaks Qdrant collection sizing.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
        dimension: int = 1536,
    ) -> None:
        import openai  # lazy import  # noqa: PLC0415

        self._model = model
        self._dimension = dimension
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            input=texts,
            model=self._model,
        )
        return [item.embedding for item in response.data]
