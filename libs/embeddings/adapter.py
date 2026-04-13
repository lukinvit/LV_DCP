"""Embedding adapter protocol and implementations."""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, Protocol, runtime_checkable


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

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        import openai  # lazy import  # noqa: PLC0415

        self._model = model
        self._dimension = 1536  # default for text-embedding-3-small
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
