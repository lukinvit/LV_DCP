"""Factory: create an LLMClient from LLMConfig."""

from __future__ import annotations

import os

from libs.core.projects_config import LLMConfig
from libs.llm.anthropic_client import AnthropicClient
from libs.llm.base import LLMClient
from libs.llm.errors import LLMConfigError
from libs.llm.ollama_client import OllamaClient
from libs.llm.openai_client import OpenAIClient


def create_client(config: LLMConfig) -> LLMClient:
    """Create an LLMClient for the configured provider.

    Raises LLMConfigError if the provider is unknown or an API-key env var
    is missing for providers that require one.
    """
    if config.provider == "openai":
        api_key = os.environ.get(config.api_key_env_var)
        if not api_key:
            raise LLMConfigError(
                f"{config.api_key_env_var} env var not set. "
                f"Run: export {config.api_key_env_var}=sk-..."
            )
        return OpenAIClient(api_key=api_key)

    if config.provider == "anthropic":
        api_key = os.environ.get(config.api_key_env_var)
        if not api_key:
            raise LLMConfigError(
                f"{config.api_key_env_var} env var not set. "
                f"Run: export {config.api_key_env_var}=sk-ant-..."
            )
        return AnthropicClient(api_key=api_key)

    if config.provider == "ollama":
        return OllamaClient()

    raise LLMConfigError(f"unknown provider: {config.provider!r}")
