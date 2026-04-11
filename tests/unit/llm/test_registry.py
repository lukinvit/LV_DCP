from __future__ import annotations

import pytest
from libs.core.projects_config import LLMConfig
from libs.llm.anthropic_client import AnthropicClient
from libs.llm.errors import LLMConfigError
from libs.llm.ollama_client import OllamaClient
from libs.llm.openai_client import OpenAIClient
from libs.llm.registry import create_client


def test_openai_client_created_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = LLMConfig(provider="openai", api_key_env_var="OPENAI_API_KEY")
    client = create_client(cfg)
    assert isinstance(client, OpenAIClient)


def test_openai_raises_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = LLMConfig(provider="openai", api_key_env_var="OPENAI_API_KEY")
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        create_client(cfg)


def test_anthropic_client_created_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = LLMConfig(provider="anthropic", api_key_env_var="ANTHROPIC_API_KEY")
    client = create_client(cfg)
    assert isinstance(client, AnthropicClient)


def test_anthropic_raises_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = LLMConfig(provider="anthropic", api_key_env_var="ANTHROPIC_API_KEY")
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        create_client(cfg)


def test_ollama_client_created_without_env() -> None:
    cfg = LLMConfig(provider="ollama", api_key_env_var="UNUSED")
    client = create_client(cfg)
    assert isinstance(client, OllamaClient)


def test_unknown_provider_raises() -> None:
    cfg = LLMConfig(provider="unknown", api_key_env_var="x")
    with pytest.raises(LLMConfigError, match="unknown provider"):
        create_client(cfg)
