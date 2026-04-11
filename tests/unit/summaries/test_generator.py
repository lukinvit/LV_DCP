"""Test for single-file summary generator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from libs.llm.base import SummaryResult
from libs.llm.models import UsageRecord
from libs.summaries.generator import generate_file_summary


@pytest.fixture
def fake_usage() -> UsageRecord:
    return UsageRecord(
        input_tokens=800,
        output_tokens=180,
        cached_input_tokens=0,
        cost_usd=0.00032,
        model="gpt-4o-mini",
        provider="openai",
        timestamp=time.time(),
    )


async def test_generator_forwards_to_client(fake_usage: UsageRecord) -> None:
    expected = SummaryResult(text="Stub summary.", usage=fake_usage)
    mock_client = AsyncMock()
    mock_client.summarize = AsyncMock(return_value=expected)

    result = await generate_file_summary(
        file_path="apps/cli/main.py",
        content="import typer",
        client=mock_client,
        model="gpt-4o-mini",
        prompt_version="v1",
    )

    assert result is expected
    mock_client.summarize.assert_awaited_once_with(
        content="import typer",
        model="gpt-4o-mini",
        prompt_version="v1",
        file_path="apps/cli/main.py",
    )
