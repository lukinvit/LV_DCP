"""Structlog enrichment on timeline surfaces (spec-010 T039).

Every timeline entry point emits one structured log line with the
fields the spec requires (``project_root``, ``commit_sha``,
``duration_ms``, plus per-call counters).
"""

from __future__ import annotations

from pathlib import Path

import structlog
from libs.symbol_timeline.differ import AstSnapshot, SymbolSnapshot
from libs.symbol_timeline.query import (
    diff,
    find_removed_since,
    symbol_timeline,
)
from libs.symbol_timeline.reconcile import reconcile
from libs.symbol_timeline.scan_bracket import emit_timeline
from libs.symbol_timeline.sinks import MemoryTimelineSink
from libs.symbol_timeline.store import SymbolTimelineStore


def _mk_symbol(symbol_id: str, file_path: str = "pkg/a.py") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol_id=symbol_id,
        file_path=file_path,
        content_hash=symbol_id,
        qualified_name=f"pkg.a.{symbol_id}",
    )


def test_scan_bracket_emits_structured_log_with_stats() -> None:
    sink = MemoryTimelineSink()
    prev = AstSnapshot(symbols={}, commit_sha=None)
    curr = AstSnapshot(
        symbols={"s1": _mk_symbol("s1"), "s2": _mk_symbol("s2")},
        commit_sha="abc123",
    )

    with structlog.testing.capture_logs() as captured:
        emit_timeline(
            sink=sink,
            project_root="/abs/p",
            commit_sha="abc123",
            prev=prev,
            curr=curr,
            started_at=100.0,
            finished_at=100.5,
            timestamp=100.5,
            similarity_threshold=0.85,
        )

    scan_logs = [e for e in captured if e.get("event") == "timeline.scan_bracket"]
    assert len(scan_logs) == 1
    ev = scan_logs[0]
    assert ev["project_root"] == "/abs/p"
    assert ev["commit_sha"] == "abc123"
    assert ev["added"] == 2
    assert ev["modified"] == 0
    assert ev["removed"] == 0
    assert ev["duration_ms"] > 0


def test_reconcile_emits_git_unavailable_log(tmp_path: Path) -> None:
    """When git is missing, we must log a warning with duration_ms."""
    store = SymbolTimelineStore(tmp_path / "t.db")
    store.migrate()

    def failing_runner(_args: list[str]) -> str:
        msg = "git not installed"
        raise OSError(msg)

    with structlog.testing.capture_logs() as captured:
        report = reconcile(
            store,
            project_root=str(tmp_path),
            git_root=tmp_path,
            git_runner=failing_runner,
        )

    assert report.git_available is False
    warn_logs = [e for e in captured if e.get("event") == "timeline.reconcile.git_unavailable"]
    assert len(warn_logs) == 1
    assert warn_logs[0]["project_root"] == str(tmp_path)
    assert warn_logs[0]["log_level"] == "warning"
    assert "duration_ms" in warn_logs[0]


def test_reconcile_emits_done_log(tmp_path: Path) -> None:
    """When git is reachable, reconcile emits an info-level done log."""
    store = SymbolTimelineStore(tmp_path / "t.db")
    store.migrate()

    def empty_runner(_args: list[str]) -> str:
        return ""  # no commits reachable — equivalent to fresh repo

    with structlog.testing.capture_logs() as captured:
        reconcile(
            store,
            project_root=str(tmp_path),
            git_root=tmp_path,
            git_runner=empty_runner,
        )

    done_logs = [e for e in captured if e.get("event") == "timeline.reconcile.done"]
    assert len(done_logs) == 1
    ev = done_logs[0]
    assert ev["log_level"] == "info"
    assert ev["project_root"] == str(tmp_path)
    assert ev["reachable_commit_count"] == 0
    assert ev["orphaned_newly_flagged"] == 0
    assert "duration_ms" in ev


def test_find_removed_since_emits_log_on_bad_ref(tmp_path: Path) -> None:
    """Unresolvable ref must still produce a structured log entry."""
    store = SymbolTimelineStore(tmp_path / "t.db")
    store.migrate()

    with structlog.testing.capture_logs() as captured:
        find_removed_since(
            store,
            project_root=str(tmp_path),
            ref="no-such-ref",
            git_root=tmp_path,
        )

    logs = [e for e in captured if e.get("event") == "timeline.query.removed_since"]
    assert len(logs) == 1
    ev = logs[0]
    assert ev["ref"] == "no-such-ref"
    assert ev["ref_not_found"] is True
    assert ev["removed_count"] == 0
    assert "duration_ms" in ev


def test_diff_emits_log_on_bad_refs(tmp_path: Path) -> None:
    store = SymbolTimelineStore(tmp_path / "t.db")
    store.migrate()

    with structlog.testing.capture_logs() as captured:
        diff(
            store,
            project_root=str(tmp_path),
            from_ref="bad-ref",
            to_ref="also-bad",
            git_root=tmp_path,
        )

    logs = [e for e in captured if e.get("event") == "timeline.query.diff"]
    assert len(logs) == 1
    ev = logs[0]
    assert ev["from_ref"] == "bad-ref"
    assert ev["to_ref"] == "also-bad"
    assert ev["ref_not_found"] is True
    assert ev["total_added"] == 0
    assert "duration_ms" in ev


def test_symbol_timeline_emits_log_on_not_found(tmp_path: Path) -> None:
    store = SymbolTimelineStore(tmp_path / "t.db")
    store.migrate()

    with structlog.testing.capture_logs() as captured:
        symbol_timeline(
            store,
            project_root=str(tmp_path),
            symbol="missing_symbol",
        )

    logs = [e for e in captured if e.get("event") == "timeline.query.symbol_timeline"]
    assert len(logs) == 1
    ev = logs[0]
    assert ev["symbol"] == "missing_symbol"
    assert ev["not_found"] is True
    assert ev["event_count"] == 0
    assert "duration_ms" in ev
