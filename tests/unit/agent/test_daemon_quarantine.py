"""Daemon quarantine: a project that raises ``CacheCorruptError`` is skipped
on subsequent edit-blocks until the daemon restarts.

Reproduces the X5_BM crash pattern (corrupt SQLite cache → endless retry on
every FS event → log spam + wasted CPU). The fix is in-process state in
``apps.agent.daemon`` that records the failure once and short-circuits
future scan passes for that project.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import apps.agent.daemon as daemon_mod
import pytest
from apps.agent.daemon import process_pending_events, reset_quarantine
from apps.agent.handler import DebounceBuffer
from libs.storage.sqlite_cache import CacheCorruptError


@pytest.fixture(autouse=True)
def _clear_quarantine() -> Iterator[None]:
    reset_quarantine()
    yield
    reset_quarantine()


def test_cache_corrupt_quarantines_project_and_skips_on_next_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First edit-block raises CacheCorruptError → project quarantined +
    logged. Second edit-block on same project → ``[skip]`` line, no scan
    attempted.
    """
    project_root = (tmp_path / "x5bm").resolve()
    project_root.mkdir()
    (project_root / "hello.py").write_text("def hi() -> None: ...\n")

    call_count = {"n": 0}

    def fake_scan_project(
        root: Path, *, mode: str = "incremental", only: list[str] | None = None
    ) -> object:
        call_count["n"] += 1
        raise CacheCorruptError(
            f"SqliteCache at {root}/.context/cache.db failed quick_check: "
            f"invalid page number 8073. Delete {root}/.context and re-run "
            f"`ctx scan` to rebuild."
        )

    monkeypatch.setattr(daemon_mod, "scan_project", fake_scan_project)

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(project_root, "hello.py", "modified")

    log_lines: list[str] = []
    process_pending_events(buffer, logger=log_lines.append)

    # First pass: scan attempted exactly once, raised, project quarantined.
    assert call_count["n"] == 1
    assert any("[quarantine]" in line for line in log_lines), log_lines
    assert any("invalid page number 8073" in line for line in log_lines), log_lines

    # Second pass on the same project: NO new scan attempt, skip line emitted.
    log_lines.clear()
    buffer.add(project_root, "hello.py", "modified")
    process_pending_events(buffer, logger=log_lines.append)

    assert call_count["n"] == 1, "scan_project must NOT be called for quarantined project"
    assert any("[skip]" in line and "quarantined" in line for line in log_lines), log_lines


def test_quarantine_is_per_project_not_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt project must not block scans of OTHER healthy projects in
    the same daemon process.
    """
    bad_root = (tmp_path / "bad").resolve()
    bad_root.mkdir()
    (bad_root / "a.py").write_text("x = 1\n")
    good_root = (tmp_path / "good").resolve()
    good_root.mkdir()
    (good_root / "b.py").write_text("y = 2\n")

    scanned: list[Path] = []

    class _Result:
        files_reparsed = 0
        wiki_dirty_count = 0

    def fake_scan_project(
        root: Path, *, mode: str = "incremental", only: list[str] | None = None
    ) -> object:
        scanned.append(root)
        if root == bad_root:
            raise CacheCorruptError(f"corrupt at {root}")
        return _Result()

    monkeypatch.setattr(daemon_mod, "scan_project", fake_scan_project)

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(bad_root, "a.py", "modified")
    buffer.add(good_root, "b.py", "modified")

    log_lines: list[str] = []
    process_pending_events(buffer, logger=log_lines.append)

    # Both got scanned the first time around (bad failed, good succeeded).
    assert bad_root in scanned
    assert good_root in scanned

    # Second pass: bad is skipped, good still scans.
    scanned.clear()
    buffer.add(bad_root, "a.py", "modified")
    buffer.add(good_root, "b.py", "modified")
    process_pending_events(buffer, logger=log_lines.append)

    assert bad_root not in scanned, "bad project must remain quarantined"
    assert good_root in scanned, "good project must continue to scan"


def test_reset_quarantine_clears_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After daemon restart (modeled by ``reset_quarantine``), a previously
    quarantined project gets a fresh shot — important because the user's
    recovery path is to delete ``.context/`` and restart the daemon.
    """
    project_root = (tmp_path / "x5bm").resolve()
    project_root.mkdir()
    (project_root / "f.py").write_text("z = 3\n")

    fail_first = {"n": 0}

    class _Result:
        files_reparsed = 0
        wiki_dirty_count = 0

    def fake_scan_project(
        root: Path, *, mode: str = "incremental", only: list[str] | None = None
    ) -> object:
        fail_first["n"] += 1
        if fail_first["n"] == 1:
            raise CacheCorruptError(f"corrupt at {root}")
        return _Result()

    monkeypatch.setattr(daemon_mod, "scan_project", fake_scan_project)

    buffer = DebounceBuffer(debounce_seconds=0.0)
    buffer.add(project_root, "f.py", "modified")
    process_pending_events(buffer)

    # Simulate daemon restart: cache rebuilt by user, quarantine cleared.
    reset_quarantine()

    buffer.add(project_root, "f.py", "modified")
    process_pending_events(buffer)
    assert fail_first["n"] == 2, "post-restart pass must reattempt the scan"
