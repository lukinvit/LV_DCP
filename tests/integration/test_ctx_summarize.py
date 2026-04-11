"""Integration tests for `ctx summarize` CLI command."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from apps.cli.commands.summarize import summarize
from libs.llm.base import SummaryResult
from libs.llm.models import UsageRecord
from libs.scanning.scanner import scan_project
from libs.summaries.store import SummaryStore


def _fake_summary() -> SummaryResult:
    return SummaryResult(
        text="Stub summary.",
        usage=UsageRecord(
            input_tokens=800, output_tokens=150, cached_input_tokens=0,
            cost_usd=0.00032, model="gpt-4o-mini", provider="openai",
            timestamp=time.time(),
        ),
    )


def test_summarize_exits_nonzero_if_llm_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import typer

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"version": 1, "projects": []}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    with pytest.raises(typer.Exit) as exc_info:
        summarize(path=project, model=None, concurrency=1)
    assert exc_info.value.exit_code == 1
    captured = capsys.readouterr()
    assert "disabled" in (captured.err + captured.out).lower()


def test_summarize_generates_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "version": 1,
        "projects": [],
        "llm": {
            "provider": "openai",
            "summary_model": "gpt-4o-mini",
            "enabled": True,
            "api_key_env_var": "FAKE_KEY_FOR_TEST",
        },
    }))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("FAKE_KEY_FOR_TEST", "sk-test")

    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    (project / "b.py").write_text("def b() -> None: return None\n")
    scan_project(project, mode="full")

    mock_client = AsyncMock()
    mock_client.summarize = AsyncMock(return_value=_fake_summary())

    with patch("apps.cli.commands.summarize.create_client", return_value=mock_client):
        summarize(path=project, model=None, concurrency=1)

    captured = capsys.readouterr()
    assert "summarized" in captured.out

    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()
    rows = store.list_for_project(str(project.resolve()))
    assert len(rows) == 2
    store.close()
