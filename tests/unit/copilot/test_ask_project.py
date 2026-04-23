"""Unit tests for ``libs.copilot.ask_project``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from libs.copilot import DegradedMode, ask_project
from libs.copilot.orchestrator import _PackOutcome
from libs.scanning.scanner import scan_project


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / ".lvdcp").mkdir(parents=True)
    cfg = home / ".lvdcp" / "config.yaml"
    cfg.write_text(yaml.safe_dump({"qdrant": {"enabled": False}}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: home))


def _seed_project(root: Path) -> None:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "auth.py").write_text(
        "def login() -> bool:\n    return True\n", encoding="utf-8"
    )


def test_ask_hard_degrade_when_not_scanned(tmp_path: Path) -> None:
    report = ask_project(tmp_path, "how does login work?", auto_refresh=False)
    assert report.coverage == "unavailable"
    assert report.markdown == ""
    assert DegradedMode.NOT_SCANNED in report.degraded_modes
    assert any("not scanned" in s.lower() for s in report.suggestions)


def test_ask_auto_refresh_runs_scan(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    report = ask_project(tmp_path, "login", auto_refresh=True)
    # After auto-refresh, we expect the project to be indexed and the pack
    # pipeline to produce *something*.
    assert report.coverage != "unavailable"
    assert report.markdown != ""
    assert DegradedMode.NOT_SCANNED not in report.degraded_modes


def test_ask_uses_injected_pack_invoker(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    scan_project(tmp_path, mode="full")

    captured: dict[str, object] = {}

    def _fake(root: Path, query: str, mode: str, limit: int) -> _PackOutcome:
        captured["root"] = root
        captured["query"] = query
        captured["mode"] = mode
        captured["limit"] = limit
        return _PackOutcome(
            markdown="# fake pack\n",
            trace_id="trace-fake-01",
            coverage="high",
            retrieved_files=["pkg/auth.py"],
        )

    report = ask_project(
        tmp_path,
        "how does login work?",
        mode="navigate",
        limit=7,
        _pack_invoker=_fake,
    )
    assert captured["query"] == "how does login work?"
    assert captured["limit"] == 7
    assert report.trace_id == "trace-fake-01"
    assert report.coverage == "high"
    assert "fake pack" in report.markdown
    assert DegradedMode.AMBIGUOUS not in report.degraded_modes


def test_ask_surfaces_ambiguous_coverage(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    scan_project(tmp_path, mode="full")

    def _fake(_root: Path, _q: str, _m: str, _l: int) -> _PackOutcome:
        return _PackOutcome(
            markdown="# pack\n",
            trace_id="tr",
            coverage="ambiguous",
            retrieved_files=[],
        )

    report = ask_project(tmp_path, "vague", _pack_invoker=_fake)
    assert DegradedMode.AMBIGUOUS in report.degraded_modes
    # Each suggestion should be unique.
    assert len(report.suggestions) == len(set(report.suggestions))
