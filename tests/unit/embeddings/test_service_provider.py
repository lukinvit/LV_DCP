"""Tests for _build_adapter provider routing (openai / ollama / fake / bge_m3)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from libs.core.projects_config import EmbeddingConfig
from libs.embeddings.adapter import (
    FakeBgeM3Adapter,
    FakeEmbeddingAdapter,
    OpenAIEmbeddingAdapter,
)
from libs.embeddings.service import (
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_DUMMY_API_KEY,
    _build_adapter,
    _is_multi_vector,
)


class TestFakeProvider:
    def test_fake_provider_returns_fake_adapter(self) -> None:
        adapter = _build_adapter(EmbeddingConfig(provider="fake", dimension=256))
        assert isinstance(adapter, FakeEmbeddingAdapter)
        assert adapter.dimension == 256

    def test_unknown_provider_falls_back_to_fake(self) -> None:
        adapter = _build_adapter(EmbeddingConfig(provider="bogus", dimension=128))
        assert isinstance(adapter, FakeEmbeddingAdapter)


class TestOpenAIProvider:
    def test_passes_dimension_to_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = EmbeddingConfig(
            provider="openai",
            model="text-embedding-3-small",
            dimension=1536,
        )
        adapter = _build_adapter(cfg)
        assert isinstance(adapter, OpenAIEmbeddingAdapter)
        assert adapter.dimension == 1536

    def test_non_default_dimension_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Regression: OpenAIEmbeddingAdapter used to hardcode 1536.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = EmbeddingConfig(
            provider="openai",
            model="text-embedding-3-large",
            dimension=3072,
        )
        adapter = _build_adapter(cfg)
        assert adapter.dimension == 3072


class TestOllamaProvider:
    def test_ollama_provider_uses_openai_adapter(self) -> None:
        cfg = EmbeddingConfig(
            provider="ollama",
            model="nomic-embed-text",
            dimension=768,
            base_url="https://ollama.example.test/v1",
        )
        adapter = _build_adapter(cfg)
        # Ollama provider reuses the OpenAI-compat adapter.
        assert isinstance(adapter, OpenAIEmbeddingAdapter)
        assert adapter.model_name == "nomic-embed-text"
        assert adapter.dimension == 768

    def test_ollama_provider_defaults_base_url(self) -> None:
        cfg = EmbeddingConfig(
            provider="ollama",
            model="nomic-embed-text",
            dimension=768,
        )
        # base_url empty → should default to localhost Ollama.
        adapter = _build_adapter(cfg)
        assert isinstance(adapter, OpenAIEmbeddingAdapter)
        # The URL is stored inside the underlying openai client; we verify
        # indirectly by checking the helper constant is reasonable.
        assert OLLAMA_DEFAULT_BASE_URL.startswith("http://localhost:11434")

    def test_ollama_dummy_api_key_constant_nonempty(self) -> None:
        # The openai SDK rejects empty api_key; the dummy must be non-empty.
        assert OLLAMA_DUMMY_API_KEY
        assert isinstance(OLLAMA_DUMMY_API_KEY, str)

    def test_ollama_provider_does_not_require_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Explicitly clear OPENAI_API_KEY so we prove ollama doesn't touch it.
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = EmbeddingConfig(
            provider="ollama",
            model="nomic-embed-text",
            dimension=768,
        )
        # Should construct fine without any OpenAI env var.
        adapter = _build_adapter(cfg)
        assert isinstance(adapter, OpenAIEmbeddingAdapter)


# --- T013 / T015: bge-m3 routing ----------------------------------------


class TestBgeM3Provider:
    def test_fake_bge_m3_provider_returns_fake_adapter(self) -> None:
        cfg = EmbeddingConfig(provider="fake_bge_m3", dimension=64)
        adapter = _build_adapter(cfg)
        assert isinstance(adapter, FakeBgeM3Adapter)
        assert adapter.dimension == 64

    def test_bge_m3_provider_lazy_imports_real_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stub FlagEmbedding so the real BgeM3Adapter constructor doesn't try
        # to download ~2.3 GB of weights.
        model = MagicMock()
        module = MagicMock()
        module.BGEM3FlagModel = MagicMock(return_value=model)
        monkeypatch.setitem(sys.modules, "FlagEmbedding", module)

        from libs.embeddings.bge_m3 import BgeM3Adapter

        cfg = EmbeddingConfig(provider="bge_m3", dimension=1024, bge_m3_device="cpu")
        adapter = _build_adapter(cfg)
        assert isinstance(adapter, BgeM3Adapter)

    def test_is_multi_vector_true_for_fake_bge_m3(self) -> None:
        adapter = FakeBgeM3Adapter(dimension=32)
        assert _is_multi_vector(adapter) is True

    def test_is_multi_vector_false_for_dense_only(self) -> None:
        adapter = FakeEmbeddingAdapter(dimension=32)
        assert _is_multi_vector(adapter) is False


class TestVectorSearchRouting:
    """T015: vector_search must pick the right store method per adapter type."""

    @pytest.mark.asyncio
    async def test_routes_to_search_hybrid_when_adapter_is_multi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        from libs.core.projects_config import DaemonConfig, QdrantConfig
        from libs.embeddings import service
        from libs.embeddings.qdrant_store import QdrantStore

        store = QdrantStore(location=":memory:")
        store.search_hybrid = AsyncMock(return_value=[])  # type: ignore[method-assign]
        store.search_summaries = AsyncMock(return_value=[])  # type: ignore[method-assign]
        monkeypatch.setattr(service, "_build_store", lambda cfg: store)

        config = DaemonConfig(
            qdrant=QdrantConfig(enabled=True, url="http://unused"),
            embedding=EmbeddingConfig(provider="fake_bge_m3", dimension=64),
        )
        await service.vector_search(config=config, query="q", project_id="p")
        store.search_hybrid.assert_called_once()
        store.search_summaries.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_to_search_summaries_for_dense_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        from libs.core.projects_config import DaemonConfig, QdrantConfig
        from libs.embeddings import service
        from libs.embeddings.qdrant_store import QdrantStore

        store = QdrantStore(location=":memory:")
        store.search_hybrid = AsyncMock(return_value=[])  # type: ignore[method-assign]
        store.search_summaries = AsyncMock(return_value=[])  # type: ignore[method-assign]
        monkeypatch.setattr(service, "_build_store", lambda cfg: store)

        config = DaemonConfig(
            qdrant=QdrantConfig(enabled=True, url="http://unused"),
            embedding=EmbeddingConfig(provider="fake", dimension=64),
        )
        await service.vector_search(config=config, query="q", project_id="p")
        store.search_summaries.assert_called_once()
        store.search_hybrid.assert_not_called()
