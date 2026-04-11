# tests/unit/llm/test_ollama_client.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from libs.llm.errors import LLMProviderError
from libs.llm.ollama_client import OllamaClient


@pytest.fixture
def fake_generate_response() -> dict:
    return {
        "model": "qwen2.5-coder:7b",
        "created_at": "2026-04-11T00:00:00Z",
        "response": "Stub summary from local model.",
        "done": True,
        "prompt_eval_count": 500,
        "eval_count": 150,
    }


async def test_summarize_returns_summary_result(fake_generate_response: dict) -> None:
    client = OllamaClient()
    mock_response = MagicMock(
        status_code=200,
        json=MagicMock(return_value=fake_generate_response),
    )
    mock_response.raise_for_status = MagicMock()
    with patch(
        "libs.llm.ollama_client.httpx.AsyncClient.post",
        AsyncMock(return_value=mock_response),
    ):
        result = await client.summarize(
            content="def hi() -> None: return None",
            model="qwen2.5-coder:7b",
            prompt_version="v1",
            file_path="hi.py",
        )

    assert result.text == "Stub summary from local model."
    assert result.usage.input_tokens == 500
    assert result.usage.output_tokens == 150
    assert result.usage.cost_usd == 0.0
    assert result.usage.provider == "ollama"


async def test_test_connection_ok() -> None:
    client = OllamaClient()
    mock_response = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"models": [{"name": "qwen2.5-coder:7b"}]}),
    )
    mock_response.raise_for_status = MagicMock()
    with patch(
        "libs.llm.ollama_client.httpx.AsyncClient.get",
        AsyncMock(return_value=mock_response),
    ):
        assert await client.test_connection() is True


async def test_test_connection_raises_on_connection_error() -> None:
    import httpx

    client = OllamaClient()
    with (
        patch(
            "libs.llm.ollama_client.httpx.AsyncClient.get",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ),
        pytest.raises(LLMProviderError, match="refused"),
    ):
        await client.test_connection()


async def test_rerank_raises_not_implemented() -> None:
    client = OllamaClient()
    with pytest.raises(NotImplementedError):
        await client.rerank(query="q", candidates=[], model="qwen2.5-coder:7b")
