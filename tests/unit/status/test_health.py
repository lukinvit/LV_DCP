from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from apps.agent.config import add_project, update_last_scan
from libs.scanning.scanner import scan_project
from libs.status.health import build_health_card


def test_build_health_card_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate scan_history write for this test
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("def hi() -> None:\n    return None\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    update_last_scan(config_path, project, status="ok", ts_iso=now_iso)

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.root == str(project.resolve())
    assert card.name == project.name
    assert card.files >= 1
    assert card.symbols >= 1
    assert card.last_scan_status == "ok"
    assert card.stale is False


def test_build_health_card_marks_stale_after_24h(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)
    stale_iso = (datetime.now(UTC) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    update_last_scan(config_path, project, status="ok", ts_iso=stale_iso)

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.stale is True


def test_build_health_card_unregistered_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "empty_config.yaml"  # never add_project

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.last_scan_status == "unregistered"
    assert card.last_scan_at_iso is None
    assert card.files >= 1  # cache.db still readable


def test_slug_normalizes_name() -> None:
    from libs.status.health import _slugify

    assert _slugify("LV_DCP") == "lv-dcp"
    assert _slugify("Some Project") == "some-project"
    assert _slugify("x/y.z") == "x-y-z"
