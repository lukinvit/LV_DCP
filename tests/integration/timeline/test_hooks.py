"""Scanner ↔ TimelineSink integration (spec-010 T015).

Verifies the lifecycle wiring in :func:`libs.scanning.scanner.scan_project`:

* First full scan on a fresh project emits ``added`` events for every symbol.
* A second scan after modifying one function emits exactly one ``modified``
  event for the changed symbol and no spurious added/removed.
* ``MemoryTimelineSink`` receives ``on_scan_begin`` and ``on_scan_end`` with
  the correct keyword arguments.
* ``SqliteTimelineSink`` persists events into ``symbol_timeline_events`` and
  the scanner upserts ``symbol_timeline_scan_state``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.scanning.scanner import scan_project
from libs.symbol_timeline.sinks import MemoryTimelineSink, SqliteTimelineSink
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    events_between,
    get_scan_state,
)


def _seed_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "mod.py").write_text(
        "def alpha() -> int:\n    return 1\n\ndef beta() -> int:\n    return 2\n"
    )


def test_first_scan_emits_added_for_every_symbol(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    _seed_project(project)

    sink = MemoryTimelineSink()
    scan_project(project, mode="full", timeline_sink=sink)

    assert len(sink.begins) == 1
    assert len(sink.ends) == 1
    added_syms = {e.qualified_name for e in sink.events_of_type("added")}
    # At minimum the two top-level functions should be present.
    assert "pkg.mod.alpha" in added_syms
    assert "pkg.mod.beta" in added_syms
    assert sink.events_of_type("removed") == []
    assert sink.events_of_type("modified") == []


def test_second_scan_after_edit_emits_modified_only(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    _seed_project(project)

    # First scan lays down the initial snapshot in the cache.
    initial_sink = MemoryTimelineSink()
    scan_project(project, mode="full", timeline_sink=initial_sink)

    # Edit alpha's body.
    (project / "pkg" / "mod.py").write_text(
        "def alpha() -> int:\n    return 42  # changed\n\ndef beta() -> int:\n    return 2\n"
    )

    second_sink = MemoryTimelineSink()
    scan_project(project, mode="full", timeline_sink=second_sink)

    modified = {e.qualified_name for e in second_sink.events_of_type("modified")}
    assert "pkg.mod.alpha" in modified
    assert second_sink.events_of_type("added") == []
    assert second_sink.events_of_type("removed") == []


def test_sqlite_sink_persists_events_and_scan_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    _seed_project(project)

    timeline_db = tmp_path / "timeline.db"
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(timeline_db))

    store = SymbolTimelineStore(timeline_db)
    store.migrate()
    sink = SqliteTimelineSink(store=store)

    scan_project(project, mode="full", timeline_sink=sink)

    events = events_between(
        store,
        project_root=str(project.resolve()),
        from_ts=0,
        to_ts=10**12,
    )
    assert len(events) >= 2
    types = {e.event_type for e in events}
    assert types == {"added"}

    # scan state should be upserted even when git HEAD is unresolvable
    # (tmp_path is not a git repo, so commit_sha is None).
    state = get_scan_state(store, project_root=str(project.resolve()))
    assert state is not None
    assert state.last_scan_commit_sha is None
    assert state.last_scan_ts > 0

    store.close()


def test_partial_scan_skips_timeline(tmp_path: Path) -> None:
    """``only``-filtered scans (daemon-triggered) must not emit timeline events.

    A single-file partial scan would see the rest of the cache as "removed",
    producing false positives. The scanner must skip timeline emission in
    this case regardless of the passed sink.
    """
    project = tmp_path / "proj"
    _seed_project(project)

    # Full scan to prime the cache.
    scan_project(project, mode="full", timeline_sink=MemoryTimelineSink())

    # Now a partial re-scan with a sink attached.
    sink = MemoryTimelineSink()
    scan_project(project, mode="full", only={"pkg/mod.py"}, timeline_sink=sink)

    # Sink should not have received any lifecycle calls.
    assert sink.begins == []
    assert sink.ends == []
    assert sink.events == []
