from __future__ import annotations

import time
from pathlib import Path

import pytest
from libs.scan_history.store import ScanHistoryStore, events_since
from libs.scanning.scanner import scan_project


def test_manual_scan_appends_scan_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("def hi() -> None:\n    return None\n")

    store_db = tmp_path / "scan_history.db"
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(store_db))

    start = time.time()
    scan_project(project, mode="full")

    store = ScanHistoryStore(store_db)
    store.migrate()
    events = events_since(
        store,
        project_root=str(project.resolve()),
        since_ts=start - 1,
    )
    assert len(events) == 1
    assert events[0].status == "ok"
    assert events[0].source == "manual"
    assert events[0].files_scanned >= 1


def test_daemon_scan_appends_scan_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.agent.config import add_project
    from apps.agent.daemon import process_pending_events
    from apps.agent.handler import DebounceBuffer

    project = tmp_path / "proj"
    project.mkdir()
    (project / "hello.py").write_text("def hi() -> None: return None\n")

    store_db = tmp_path / "scan_history.db"
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(store_db))
    add_project(config_path, project)

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(project.resolve(), "hello.py", "modified")

    start = time.time()
    process_pending_events(buffer, config_path=config_path)

    store = ScanHistoryStore(store_db)
    store.migrate()
    events = events_since(
        store,
        project_root=str(project.resolve()),
        since_ts=start - 1,
    )
    assert len(events) == 1
    assert events[0].source == "daemon"
    assert events[0].status == "ok"
