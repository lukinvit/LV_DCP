from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from libs.llm.anthropic_client import AnthropicClient
from libs.llm.errors import LLMProviderError


@pytest.fixture
def mock_anthropic_client() -> MagicMock:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Stub summary.")]
    mock_response.usage = MagicMock(
        input_tokens=800,
        output_tokens=150,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    mock = MagicMock()
    mock.messages.create = AsyncMock(return_value=mock_response)
    mock.messages.count_tokens = AsyncMock(return_value=MagicMock(input_tokens=10))
    return mock


async def test_summarize_returns_summary_result(mock_anthropic_client: MagicMock) -> None:
    client = AnthropicClient(api_key="sk-ant-test")
    client._client = mock_anthropic_client

    result = await client.summarize(
        content="def hi() -> None: return None",
        model="claude-haiku-4-5",
        prompt_version="v1",
        file_path="hi.py",
    )

    assert result.text == "Stub summary."
    assert result.usage.input_tokens == 800
    assert result.usage.output_tokens == 150
    assert result.usage.provider == "anthropic"
    assert result.usage.model == "claude-haiku-4-5"
    assert result.usage.cost_usd > 0


async def test_summarize_with_cache_read_tokens(mock_anthropic_client: MagicMock) -> None:
    mock_anthropic_client.messages.create.return_value.usage.cache_read_input_tokens = 600
    client = AnthropicClient(api_key="sk-ant-test")
    client._client = mock_anthropic_client

    result = await client.summarize(
        content="x", model="claude-haiku-4-5", prompt_version="v1", file_path="x.py"
    )
    assert result.usage.cached_input_tokens == 600


async def test_test_connection_pings_via_count_tokens(mock_anthropic_client: MagicMock) -> None:
    client = AnthropicClient(api_key="sk-ant-test")
    client._client = mock_anthropic_client
    assert await client.test_connection() is True


async def test_test_connection_raises_on_failure() -> None:
    from anthropic import AuthenticationError

    client = AnthropicClient(api_key="sk-bad")
    mock = MagicMock()
    mock.messages.count_tokens = AsyncMock(
        side_effect=AuthenticationError(
            message="invalid api key",
            response=MagicMock(status_code=401),
            body=None,
        )
    )
    client._client = mock
    with pytest.raises(LLMProviderError, match="invalid api key"):
        await client.test_connection()


async def test_rerank_raises_not_implemented() -> None:
    client = AnthropicClient(api_key="sk-ant-test")
    with pytest.raises(NotImplementedError):
        await client.rerank(query="q", candidates=[], model="claude-haiku-4-5")
