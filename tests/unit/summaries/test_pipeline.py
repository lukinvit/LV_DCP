from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from libs.llm.base import SummaryResult
from libs.llm.models import UsageRecord
from libs.scanning.scanner import scan_project
from libs.summaries.pipeline import summarize_project
from libs.summaries.store import SummaryStore


def _fake_summary(
    text: str = "Stub.", input_tokens: int = 800, output_tokens: int = 150
) -> SummaryResult:
    return SummaryResult(
        text=text,
        usage=UsageRecord(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=0,
            cost_usd=0.00032,
            model="gpt-4o-mini",
            provider="openai",
            timestamp=time.time(),
        ),
    )


async def test_cold_run_summarizes_each_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    (project / "b.py").write_text("def b() -> None: return None\n")
    scan_project(project, mode="full")

    mock_client = AsyncMock()
    mock_client.summarize = AsyncMock(return_value=_fake_summary())

    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    result = await summarize_project(
        project.resolve(),
        client=mock_client,
        model="gpt-4o-mini",
        prompt_version="v1",
        store=store,
        concurrency=2,
    )

    assert result.files_summarized == 2
    assert result.files_cached == 0
    assert mock_client.summarize.await_count == 2
    assert result.total_cost_usd > 0


async def test_warm_run_hits_cache_skips_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    scan_project(project, mode="full")

    mock_client = AsyncMock()
    mock_client.summarize = AsyncMock(return_value=_fake_summary())

    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    # Cold run
    await summarize_project(
        project.resolve(),
        client=mock_client,
        model="gpt-4o-mini",
        prompt_version="v1",
        store=store,
        concurrency=1,
    )
    assert mock_client.summarize.await_count == 1

    # Warm run — file unchanged
    result = await summarize_project(
        project.resolve(),
        client=mock_client,
        model="gpt-4o-mini",
        prompt_version="v1",
        store=store,
        concurrency=1,
    )
    assert result.files_cached == 1
    assert result.files_summarized == 0
    assert mock_client.summarize.await_count == 1  # not called again
    assert result.total_cost_usd == 0.0


async def test_pipeline_continues_on_single_file_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from libs.llm.errors import LLMProviderError

    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    (project / "b.py").write_text("def b() -> None: return None\n")
    scan_project(project, mode="full")

    call_count = 0

    async def fake_summarize(**kwargs: object) -> SummaryResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMProviderError("rate limited")
        return _fake_summary()

    mock_client = AsyncMock()
    mock_client.summarize = fake_summarize

    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()

    result = await summarize_project(
        project.resolve(),
        client=mock_client,
        model="gpt-4o-mini",
        prompt_version="v1",
        store=store,
        concurrency=1,
    )
    assert result.files_summarized == 1  # one succeeded
    assert len(result.errors) == 1
