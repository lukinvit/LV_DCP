"""Tests for the `ctx timeline` CLI group (spec-010 T034)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from apps.cli.main import app
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
    upsert_scan_state,
)
from typer.testing import CliRunner


@pytest.fixture
def timeline_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "timeline.db"
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(db))
    store = SymbolTimelineStore(db)
    store.migrate()
    store.close()
    return db


def _seed_events(db: Path, project_root: str) -> None:
    store = SymbolTimelineStore(db)
    for i, et in enumerate(["added", "added", "modified", "removed"]):
        append_event(
            store,
            event=TimelineEvent(
                project_root=project_root,
                symbol_id=f"s{i}",
                event_type=et,
                commit_sha="sha-gone" if et == "removed" else "sha-alive",
                timestamp=float(100 + i),
                author=None,
                content_hash=None,
                file_path="pkg/mod.py",
                orphaned=(et == "removed"),
            ),
        )
    upsert_scan_state(
        store,
        project_root=project_root,
        last_scan_commit_sha="sha-alive",
        last_scan_ts=200.0,
    )
    store.close()


def test_enable_disable_writes_flag_file(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "disable", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".context" / "timeline.enabled").read_text().strip() == "off"

    result = runner.invoke(app, ["timeline", "enable", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".context" / "timeline.enabled").read_text().strip() == "on"


def test_status_text_output_shows_counts(tmp_path: Path, timeline_db: Path) -> None:
    _seed_events(timeline_db, str(tmp_path.resolve()))
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "status", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "total events:     4" in out
    assert "added" in out
    assert "orphaned events:  1" in out
    assert "last scan sha:    sha-alive" in out


def test_status_json_output_is_machine_readable(tmp_path: Path, timeline_db: Path) -> None:
    _seed_events(timeline_db, str(tmp_path.resolve()))
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "status", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["total_events"] == 4
    assert payload["orphaned_events"] == 1
    assert payload["last_scan_commit_sha"] == "sha-alive"
    assert payload["event_counts"]["added"] == 2
    assert payload["enabled"] is True


def test_status_reports_disabled_after_disable(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["timeline", "disable", "--project", str(tmp_path)])
    result = runner.invoke(app, ["timeline", "status", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["enabled"] is False


def test_prune_default_removes_only_orphaned(tmp_path: Path, timeline_db: Path) -> None:
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    runner = CliRunner()
    # Very small --older-than so the 100-second timestamps count as "old".
    now = time.time()
    # Move the events to be 10 days old so --older-than=1 catches them.
    store = SymbolTimelineStore(timeline_db)
    store._connect().execute(
        "UPDATE symbol_timeline_events SET timestamp = ? WHERE project_root = ?",
        (now - 10 * 86400, project_root),
    )
    store._connect().commit()
    store.close()

    result = runner.invoke(
        app,
        ["timeline", "prune", "--older-than", "1", "--project", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout
    assert "deleted 1 events" in result.stdout  # only the one orphaned
    assert "orphaned only" in result.stdout


def test_prune_include_live_removes_everything(tmp_path: Path, timeline_db: Path) -> None:
    project_root = str(tmp_path.resolve())
    _seed_events(timeline_db, project_root)
    now = time.time()
    store = SymbolTimelineStore(timeline_db)
    store._connect().execute(
        "UPDATE symbol_timeline_events SET timestamp = ? WHERE project_root = ?",
        (now - 10 * 86400, project_root),
    )
    store._connect().commit()
    store.close()

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "timeline",
            "prune",
            "--older-than",
            "1",
            "--include-live",
            "--project",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "deleted 4 events" in result.stdout


def test_prune_rejects_non_positive(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["timeline", "prune", "--older-than", "0", "--project", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "must be positive" in result.output


def test_reconcile_reports_git_unavailable(
    tmp_path: Path, timeline_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tmp_path is not a git repo, and we'd normally fall through to system git;
    # force PATH empty so `git` is not found → git_available=False.
    monkeypatch.setenv("PATH", "/nonexistent")
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "reconcile", "--project", str(tmp_path)])
    assert result.exit_code == 1
    assert "git unavailable" in result.output


def test_backfill_prints_scan_hint(tmp_path: Path, timeline_db: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["timeline", "backfill", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "ctx scan" in result.stdout
    assert str(tmp_path.resolve()) in result.stdout
