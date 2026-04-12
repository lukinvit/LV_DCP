"""Embedding adapter protocol and implementations."""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Protocol for embedding providers."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


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


class OpenAIEmbeddingAdapter:
    """Wraps openai.AsyncOpenAI for text-embedding-3-small.

    The ``openai`` package is imported lazily so the module can be loaded
    without it installed.
    """

    MODEL = "text-embedding-3-small"
    DIMENSION = 1536

    def __init__(self, *, api_key: str | None = None) -> None:
        import openai  # lazy import

        self._client = openai.AsyncOpenAI(api_key=api_key)

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    @property
    def model_name(self) -> str:
        return self.MODEL

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:

        response = await self._client.embeddings.create(
            input=texts,
            model=self.MODEL,
        )
        return [item.embedding for item in response.data]
