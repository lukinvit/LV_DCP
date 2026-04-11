"""Integration tests for the watchdog daemon — deterministic + observer smoke test."""

import time
from pathlib import Path

from apps.agent.daemon import DaemonEventHandler, process_pending_events
from apps.agent.handler import DebounceBuffer
from libs.scanning.scanner import CACHE_REL, scan_project
from libs.storage.sqlite_cache import SqliteCache


def test_process_pending_events_runs_incremental_scan(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("def alpha() -> None:\n    return None\n")

    # Initial full scan
    scan_project(project, mode="full")

    # Simulate an event arriving in the buffer
    buffer = DebounceBuffer(debounce_seconds=0.01)
    (project / "b.py").write_text("def beta() -> None:\n    return None\n")
    buffer.add(project, "b.py", "created")

    # Flush and process
    results = process_pending_events(buffer)

    # Verify b.py now in cache
    with SqliteCache(project / CACHE_REL) as cache:
        cache.migrate()
        files = {f.path for f in cache.iter_files()}

    assert "a.py" in files
    assert "b.py" in files
    assert results[project] >= 1  # at least b.py reparsed


def test_observer_emits_events_to_buffer(tmp_path: Path) -> None:
    from watchdog.observers import Observer

    project = tmp_path / "project"
    project.mkdir()

    buffer = DebounceBuffer(debounce_seconds=0.01)
    handler = DaemonEventHandler(project, buffer)
    observer = Observer()
    observer.schedule(handler, str(project), recursive=True)
    observer.start()
    try:
        (project / "new.py").write_text("x = 1\n")
        # Poll for up to 3 seconds
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if buffer.has_pending():
                break
            time.sleep(0.05)
    finally:
        observer.stop()
        observer.join(timeout=2.0)

    pending = buffer.flush_all()
    assert project in pending
    assert "new.py" in pending[project]
