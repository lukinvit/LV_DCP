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


def _seed_obsidian_marker(project: Path, *, epoch: float) -> None:
    (project / ".context").mkdir(parents=True, exist_ok=True)
    (project / ".context" / "obsidian_last_sync").write_text(str(epoch), encoding="utf-8")


def test_build_health_card_obsidian_marker_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No marker on disk → both obsidian fields are None (backward-compatible)."""
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.obsidian_last_sync_at_iso is None
    assert card.obsidian_sync_age_hours is None


def test_build_health_card_obsidian_marker_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh marker (~2h ago) → iso populated, age_hours ≈ 2.0."""
    import time as _time

    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)

    two_hours_ago = _time.time() - 2 * 3600
    _seed_obsidian_marker(project, epoch=two_hours_ago)

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.obsidian_last_sync_at_iso is not None
    assert card.obsidian_last_sync_at_iso.endswith("Z")
    assert card.obsidian_sync_age_hours is not None
    assert 1.9 < card.obsidian_sync_age_hours < 2.1


def test_build_health_card_obsidian_marker_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marker from 3 days ago → age ≈ 72h, rendered as days by the template."""
    import time as _time

    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)

    three_days_ago = _time.time() - 72 * 3600
    _seed_obsidian_marker(project, epoch=three_days_ago)

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.obsidian_sync_age_hours is not None
    assert 71.0 < card.obsidian_sync_age_hours < 73.0


def test_build_health_card_obsidian_marker_garbage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-float marker contents must not raise — fields fall back to None."""
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)

    (project / ".context").mkdir(parents=True, exist_ok=True)
    (project / ".context" / "obsidian_last_sync").write_text("not-a-float\n", encoding="utf-8")

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.obsidian_last_sync_at_iso is None
    assert card.obsidian_sync_age_hours is None


def test_build_health_card_obsidian_marker_future_clamps_to_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clock skew: marker in the future → age is clamped to 0, never negative."""
    import time as _time

    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    config_path = tmp_path / "config.yaml"
    add_project(config_path, project)

    future = _time.time() + 60  # 1 min in the future
    _seed_obsidian_marker(project, epoch=future)

    card = build_health_card(project.resolve(), config_path=config_path)
    assert card.obsidian_sync_age_hours is not None
    assert card.obsidian_sync_age_hours == 0.0


def test_read_obsidian_sync_accepts_injected_now(tmp_path: Path) -> None:
    """The helper must accept an injected ``now`` for deterministic tests."""
    from libs.status.health import _read_obsidian_sync

    project = tmp_path / "proj"
    project.mkdir()
    _seed_obsidian_marker(project, epoch=1000.0)

    iso, age = _read_obsidian_sync(project, now=1000.0 + 3600)
    assert iso is not None
    assert age == 1.0
