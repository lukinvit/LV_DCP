from __future__ import annotations

import time
from pathlib import Path

from libs.scan_history.store import (
    ScanEvent,
    ScanHistoryStore,
    append_event,
    events_since,
)


def test_append_and_query_single_event(tmp_path: Path) -> None:
    db = tmp_path / "scan_history.db"
    store = ScanHistoryStore(db)
    store.migrate()

    now = time.time()
    append_event(
        store,
        event=ScanEvent(
            project_root="/abs/proj",
            timestamp=now,
            files_reparsed=10,
            files_scanned=100,
            duration_ms=250.5,
            status="ok",
            source="manual",
        ),
    )

    events = events_since(store, project_root="/abs/proj", since_ts=0.0)
    assert len(events) == 1
    ev = events[0]
    assert ev.files_reparsed == 10
    assert ev.files_scanned == 100
    assert abs(ev.duration_ms - 250.5) < 1e-6
    assert ev.status == "ok"
    assert ev.source == "manual"


def test_filters_by_project_root(tmp_path: Path) -> None:
    store = ScanHistoryStore(tmp_path / "db.db")
    store.migrate()
    now = time.time()
    append_event(store, event=ScanEvent("/abs/a", now, 1, 1, 10.0, "ok", "daemon"))
    append_event(store, event=ScanEvent("/abs/b", now, 2, 2, 20.0, "ok", "daemon"))

    a_events = events_since(store, project_root="/abs/a", since_ts=0)
    b_events = events_since(store, project_root="/abs/b", since_ts=0)
    assert len(a_events) == 1
    assert len(b_events) == 1
    assert a_events[0].files_reparsed == 1
    assert b_events[0].files_reparsed == 2


def test_filters_by_timestamp(tmp_path: Path) -> None:
    store = ScanHistoryStore(tmp_path / "db.db")
    store.migrate()
    now = time.time()
    append_event(store, event=ScanEvent("/abs/p", now - 3 * 86400, 1, 1, 1.0, "ok", "daemon"))
    append_event(store, event=ScanEvent("/abs/p", now - 1 * 86400, 1, 1, 1.0, "ok", "daemon"))

    two_days_ago = now - 2 * 86400
    events = events_since(store, project_root="/abs/p", since_ts=two_days_ago)
    assert len(events) == 1


def test_retention_prunes_old_events(tmp_path: Path) -> None:
    store = ScanHistoryStore(tmp_path / "db.db")
    store.migrate()
    now = time.time()
    append_event(store, event=ScanEvent("/abs/p", now - 91 * 86400, 1, 1, 1.0, "ok", "daemon"))
    append_event(store, event=ScanEvent("/abs/p", now - 30 * 86400, 2, 2, 2.0, "ok", "daemon"))

    events = events_since(store, project_root="/abs/p", since_ts=0)
    assert len(events) == 1
    assert events[0].files_reparsed == 2
