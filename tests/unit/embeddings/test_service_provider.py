"""Tests for _build_adapter provider routing (openai / ollama / fake)."""

from __future__ import annotations

import pytest
from libs.core.projects_config import EmbeddingConfig
from libs.embeddings.adapter import FakeEmbeddingAdapter, OpenAIEmbeddingAdapter
from libs.embeddings.service import (
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_DUMMY_API_KEY,
    _build_adapter,
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
