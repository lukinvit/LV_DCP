from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from libs.llm.errors import LLMProviderError
from libs.llm.openai_client import OpenAIClient


@pytest.fixture
def mock_openai_client() -> MagicMock:
    """Returns a mock OpenAI async client with a fake chat.completions.create response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Stub summary text."))]
    mock_response.model = "gpt-4o-mini"
    mock_response.usage = MagicMock(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=MagicMock(cached_tokens=0),
    )
    mock = MagicMock()
    mock.chat.completions.create = AsyncMock(return_value=mock_response)
    mock.models.list = AsyncMock(return_value=MagicMock(data=[MagicMock(id="gpt-4o-mini")]))
    return mock


async def test_summarize_returns_summary_result(mock_openai_client: MagicMock) -> None:
    client = OpenAIClient(api_key="sk-test")
    client._client = mock_openai_client

    result = await client.summarize(
        content="def hi() -> None: return None",
        model="gpt-4o-mini",
        prompt_version="v1",
        file_path="hi.py",
    )

    assert result.text == "Stub summary text."
    assert result.usage.input_tokens == 1000
    assert result.usage.output_tokens == 200
    assert result.usage.cached_input_tokens == 0
    assert result.usage.model == "gpt-4o-mini"
    assert result.usage.provider == "openai"
    assert result.usage.cost_usd > 0
    assert result.usage.timestamp > 0


async def test_summarize_reads_cached_tokens(mock_openai_client: MagicMock) -> None:
    mock_openai_client.chat.completions.create.return_value.usage.prompt_tokens_details.cached_tokens = 800
    client = OpenAIClient(api_key="sk-test")
    client._client = mock_openai_client

    result = await client.summarize(
        content="x", model="gpt-4o-mini", prompt_version="v1", file_path="x.py"
    )
    assert result.usage.cached_input_tokens == 800


async def test_test_connection_returns_true_on_success(mock_openai_client: MagicMock) -> None:
    client = OpenAIClient(api_key="sk-test")
    client._client = mock_openai_client
    assert await client.test_connection() is True


async def test_test_connection_raises_on_auth_error() -> None:
    from openai import AuthenticationError

    client = OpenAIClient(api_key="sk-bad")
    mock = MagicMock()
    mock.models.list = AsyncMock(
        side_effect=AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body=None,
        )
    )
    client._client = mock
    with pytest.raises(LLMProviderError, match="Invalid API key"):
        await client.test_connection()


async def test_rerank_empty_candidates_returns_empty() -> None:
    client = OpenAIClient(api_key="sk-test")
    result = await client.rerank(query="test", candidates=[], model="gpt-4o-mini")
    assert result == []


async def test_summarize_retries_on_rate_limit_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When OpenAI returns 429 with Retry-After header, client should wait and retry."""
    from openai import RateLimitError

    success_response = MagicMock()
    success_response.choices = [MagicMock(message=MagicMock(content="Retried ok."))]
    success_response.model = "gpt-4o-mini"
    success_response.usage = MagicMock(
        prompt_tokens=100,
        completion_tokens=50,
        prompt_tokens_details=MagicMock(cached_tokens=0),
    )

    # Build a RateLimitError with a mock response having Retry-After header
    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {"retry-after": "0.01"}

    call_count = 0

    async def mock_create(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RateLimitError(
                message="rate limit exceeded",
                response=rate_limit_response,
                body=None,
            )
        return success_response

    # Capture sleep calls to verify we honored Retry-After
    sleeps: list[float] = []

    async def mock_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("libs.llm.openai_client.asyncio.sleep", mock_sleep)

    client = OpenAIClient(api_key="sk-test")
    mock = MagicMock()
    mock.chat.completions.create = mock_create
    client._client = mock

    result = await client.summarize(
        content="x", model="gpt-4o-mini", prompt_version="v2", file_path="x.py"
    )
    assert result.text == "Retried ok."
    assert call_count == 2  # one failure + one retry
    # Sleep should have been called with value close to 0.01 (Retry-After)
    assert len(sleeps) >= 1
    assert 0.01 <= sleeps[0] <= 1.0  # small sleep from Retry-After header


async def test_summarize_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After 3 retries all failing with 429, client should raise LLMProviderError."""
    from openai import RateLimitError

    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {"retry-after": "0.01"}

    async def always_rate_limited(**kwargs: object) -> None:
        raise RateLimitError(
            message="rate limit exceeded",
            response=rate_limit_response,
            body=None,
        )

    async def mock_sleep(seconds: float) -> None:
        return

    monkeypatch.setattr("libs.llm.openai_client.asyncio.sleep", mock_sleep)

    client = OpenAIClient(api_key="sk-test")
    mock = MagicMock()
    mock.chat.completions.create = always_rate_limited
    client._client = mock

    with pytest.raises(LLMProviderError, match="rate limit"):
        await client.summarize(
            content="x", model="gpt-4o-mini", prompt_version="v2", file_path="x.py"
        )
