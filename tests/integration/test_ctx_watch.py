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


def test_process_pending_events_removes_deleted_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("def alpha() -> None: pass\n")
    (project / "b.py").write_text("def beta() -> None: pass\n")

    scan_project(project, mode="full")

    # Verify both files are in cache after the initial scan
    with SqliteCache(project / CACHE_REL) as cache:
        cache.migrate()
        files_before = {f.path for f in cache.iter_files()}
    assert "b.py" in files_before

    # Delete b.py on disk and signal it to the buffer as deleted
    (project / "b.py").unlink()
    buffer = DebounceBuffer(debounce_seconds=0.01)
    buffer.add(project, "b.py", "deleted")

    process_pending_events(buffer)

    with SqliteCache(project / CACHE_REL) as cache:
        cache.migrate()
        files_after = {f.path for f in cache.iter_files()}

    assert "a.py" in files_after
    assert "b.py" not in files_after


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
    # modified set contains new.py
    modified, _deleted = pending[project]
    assert "new.py" in modified


def test_process_pending_events_submits_wiki_task_when_threshold_met(
    tmp_path: Path,
) -> None:
    """Wiki update task is submitted when dirty_count >= threshold."""
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock, patch

    from apps.agent.daemon import process_pending_events
    from apps.agent.handler import DebounceBuffer
    from libs.core.projects_config import WikiConfig

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(tmp_path, "libs/core/a.py", "modified")

    mock_result = MagicMock()
    mock_result.files_reparsed = 1
    mock_result.wiki_dirty_count = 5  # above default threshold of 3

    wiki_config = WikiConfig(auto_update_after_scan=True, dirty_threshold=3)
    pool = ThreadPoolExecutor(max_workers=1)

    try:
        with (
            patch("apps.agent.daemon.scan_project", return_value=mock_result),
            patch("apps.agent.daemon.run_wiki_update") as mock_worker,
        ):
            pool_spy = MagicMock(wraps=pool)
            process_pending_events(
                buffer,
                wiki_pool=pool_spy,
                wiki_config=wiki_config,
            )
            pool_spy.submit.assert_called_once()
            call_args = pool_spy.submit.call_args
            assert call_args.args[0] is mock_worker
            assert call_args.args[1] == tmp_path
            assert call_args.args[2] == wiki_config
    finally:
        pool.shutdown(wait=False)


def test_process_pending_events_no_wiki_task_below_threshold(tmp_path: Path) -> None:
    """Wiki task not submitted when dirty_count < threshold."""
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock, patch

    from apps.agent.daemon import process_pending_events
    from apps.agent.handler import DebounceBuffer
    from libs.core.projects_config import WikiConfig

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(tmp_path, "libs/core/a.py", "modified")

    mock_result = MagicMock()
    mock_result.files_reparsed = 1
    mock_result.wiki_dirty_count = 1  # below threshold of 3

    wiki_config = WikiConfig(auto_update_after_scan=True, dirty_threshold=3)
    pool = ThreadPoolExecutor(max_workers=1)

    try:
        with patch("apps.agent.daemon.scan_project", return_value=mock_result):
            pool_spy = MagicMock(wraps=pool)
            process_pending_events(
                buffer,
                wiki_pool=pool_spy,
                wiki_config=wiki_config,
            )
            pool_spy.submit.assert_not_called()
    finally:
        pool.shutdown(wait=False)
