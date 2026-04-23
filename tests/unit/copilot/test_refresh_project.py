"""Unit tests for ``libs.copilot.refresh_project`` and ``refresh_wiki``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from libs.copilot import refresh_project, refresh_wiki


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
    (root / "pkg" / "a.py").write_text("def a() -> int:\n    return 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("def b() -> int:\n    return 2\n", encoding="utf-8")


def test_refresh_no_wiki_short_circuit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_project(tmp_path)
    # Ensure the wiki path is never touched when refresh_wiki_after=False.
    called: dict[str, int] = {"wiki": 0}

    def _boom(*_a: Any, **_kw: Any) -> None:  # pragma: no cover — defensive
        called["wiki"] += 1
        raise AssertionError("refresh_wiki must not be called")

    monkeypatch.setattr("libs.copilot.orchestrator.refresh_wiki", _boom)
    report = refresh_project(tmp_path, full=False, refresh_wiki_after=False)
    assert report.scanned is True
    assert report.wiki_refreshed is False
    assert report.scan_files >= 1
    assert called["wiki"] == 0


def test_refresh_wiki_skipped_when_not_scanned(tmp_path: Path) -> None:
    report = refresh_wiki(tmp_path, all_modules=False)
    assert report.scanned is False
    assert report.wiki_refreshed is False
    assert any("not scanned" in m for m in report.messages)


def test_refresh_project_then_wiki_noop_on_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a fresh scan, dirty modules exist; the wiki refresh should touch them.

    We stub ``generate_wiki_article`` so this test stays offline (no LLM call).
    """
    _seed_project(tmp_path)

    def _stub_article(**kw: Any) -> str:
        return f"# {kw['module_path']}\n\nstubbed wiki body.\n"

    # `generate_wiki_article` is imported lazily inside
    # `_run_wiki_update_in_process`, so the only patch target that actually
    # takes effect is the source module.
    monkeypatch.setattr(
        "libs.wiki.generator.generate_wiki_article",
        _stub_article,
    )
    report = refresh_project(tmp_path, full=True, refresh_wiki_after=True)
    assert report.scanned is True
    assert report.scan_files >= 2
    assert report.wiki_refreshed is True
    # A fresh scan marks every module dirty; at least one should have been updated.
    assert report.wiki_modules_updated >= 1
