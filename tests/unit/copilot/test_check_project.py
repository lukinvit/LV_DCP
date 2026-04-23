"""Unit tests for ``libs.copilot.check_project``."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from libs.copilot import DegradedMode, check_project
from libs.scanning.scanner import scan_project


@pytest.fixture
def qdrant_off_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``$HOME`` + LVDCP_CONFIG_PATH to a tmp Qdrant-off config.

    Scanner + embedder still hard-code ``Path.home() / '.lvdcp' /
    'config.yaml'``, so both hooks are required to keep the tests offline.
    """
    home = tmp_path / "home"
    (home / ".lvdcp").mkdir(parents=True)
    cfg = home / ".lvdcp" / "config.yaml"
    cfg.write_text(yaml.safe_dump({"qdrant": {"enabled": False}}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: home))
    return cfg


def _make_project(root: Path) -> None:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "mod.py").write_text(
        "def hi() -> str:\n    return 'hi'\n",
        encoding="utf-8",
    )


def test_check_reports_not_scanned_for_empty_dir(tmp_path: Path, qdrant_off_config: Path) -> None:
    report = check_project(tmp_path)
    assert report.scanned is False
    assert report.files == 0
    assert report.symbols == 0
    assert DegradedMode.NOT_SCANNED in report.degraded_modes
    assert DegradedMode.WIKI_MISSING in report.degraded_modes


def test_check_reports_scanned_after_scan(tmp_path: Path, qdrant_off_config: Path) -> None:
    _make_project(tmp_path)
    scan_project(tmp_path, mode="full")
    report = check_project(tmp_path)
    assert report.scanned is True
    assert report.files >= 1
    assert report.symbols >= 1
    assert DegradedMode.NOT_SCANNED not in report.degraded_modes
    # Wiki is still missing right after scan (we didn't run `wiki update`).
    assert DegradedMode.WIKI_MISSING in report.degraded_modes


def test_check_surfaces_qdrant_off(tmp_path: Path, qdrant_off_config: Path) -> None:
    _make_project(tmp_path)
    scan_project(tmp_path, mode="full")
    report = check_project(tmp_path)
    assert report.qdrant_enabled is False
    assert DegradedMode.QDRANT_OFF in report.degraded_modes


def test_check_returns_absolute_paths(tmp_path: Path, qdrant_off_config: Path) -> None:
    report = check_project(tmp_path)
    assert Path(report.project_root).is_absolute()
    assert report.project_name == tmp_path.name


def test_check_reports_stale_scan(
    tmp_path: Path, qdrant_off_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``card.stale == True`` must surface ``DegradedMode.STALE_SCAN``.

    Rather than time-traveling sqlite timestamps we monkeypatch
    ``build_health_card`` at the orchestrator import site and return a
    stale card.
    """
    _make_project(tmp_path)
    scan_project(tmp_path, mode="full")

    from libs.copilot import orchestrator as orch
    from libs.status.health import build_health_card as real_build_health_card

    def _stale_card(root: Path, *, config_path: Path | None = None) -> object:
        resolved_path = config_path if config_path is not None else qdrant_off_config
        card = real_build_health_card(root, config_path=resolved_path)
        return card.model_copy(update={"stale": True})

    monkeypatch.setattr(orch, "build_health_card", _stale_card)

    report = check_project(tmp_path)
    assert report.scanned is True
    assert report.stale is True
    assert DegradedMode.STALE_SCAN in report.degraded_modes
    # STALE_SCAN and NOT_SCANNED are mutually exclusive (elif branch).
    assert DegradedMode.NOT_SCANNED not in report.degraded_modes


def test_check_reports_wiki_stale(
    tmp_path: Path, qdrant_off_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiki present + dirty modules > 0 must surface ``DegradedMode.WIKI_STALE``."""
    _make_project(tmp_path)
    scan_project(tmp_path, mode="full")

    # Fake a present wiki by writing the INDEX marker file.
    wiki_dir = tmp_path / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "INDEX.md").write_text("# wiki\n", encoding="utf-8")

    # Force the dirty-module count to be non-zero without generating wiki
    # rows: monkeypatch the helper at the orchestrator module level.
    from libs.copilot import orchestrator as orch

    monkeypatch.setattr(orch, "_count_dirty_wiki_modules", lambda _root: 3)

    report = check_project(tmp_path)
    assert report.wiki_present is True
    assert report.wiki_dirty_modules == 3
    assert DegradedMode.WIKI_STALE in report.degraded_modes
    # WIKI_STALE and WIKI_MISSING are mutually exclusive (elif branch).
    assert DegradedMode.WIKI_MISSING not in report.degraded_modes


def test_check_surfaces_wiki_refresh_in_progress(
    tmp_path: Path, qdrant_off_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live ``.refresh.lock`` must surface as ``wiki_refresh_in_progress=True``."""
    import json as _json
    import time as _time

    _make_project(tmp_path)
    scan_project(tmp_path, mode="full")

    wiki_dir = tmp_path / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / ".refresh.lock").write_text(
        _json.dumps({"pid": 12345, "started_at": _time.time(), "all_modules": False}),
        encoding="utf-8",
    )

    from libs.copilot import wiki_background

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)

    report = check_project(tmp_path)
    assert report.wiki_refresh_in_progress is True
