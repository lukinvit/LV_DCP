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
