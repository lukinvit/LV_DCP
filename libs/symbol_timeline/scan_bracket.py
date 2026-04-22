"""Scan-lifecycle glue: runs the TimelineSink Protocol around a scan pass.

The scanner calls :func:`on_begin` at the very top (after migrate) and
:func:`on_end` after the scan body finishes successfully. The helper is
a pure orchestrator - no I/O beyond what the sink itself does - so it
can be unit-tested against a :class:`MemoryTimelineSink`.

Failures inside any sink method MUST NOT crash the scan: the caller is
expected to wrap the whole bracket in ``try/except`` (see
``libs.scanning.scanner``). This module re-raises everything so tests
can assert correctness; the scanner provides the safety net.

Spec: specs/010-feature-timeline-index/plan.md §Hook Matrix / Layer 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from libs.symbol_timeline.differ import diff_ast_snapshots
from libs.symbol_timeline.rename_detect import pair_renames

if TYPE_CHECKING:
    from libs.symbol_timeline.differ import AstSnapshot
    from libs.symbol_timeline.sinks import TimelineSink
    from libs.symbol_timeline.store import TimelineEvent


def emit_timeline(  # noqa: PLR0913 - keyword-only lifecycle contract
    *,
    sink: TimelineSink,
    project_root: str,
    commit_sha: str | None,
    prev: AstSnapshot,
    curr: AstSnapshot,
    started_at: float,
    finished_at: float,
    timestamp: float,
    similarity_threshold: float,
    author: str | None = None,
) -> dict[str, int]:
    """Run the full scan-bracket protocol on ``sink``.

    1. :meth:`on_scan_begin` with ``(project_root, commit_sha, started_at)``.
    2. Diff ``prev`` vs ``curr`` (already built by the caller).
    3. Dispatch add/modify/remove/move events to the sink.
    4. Rename detection on the add/remove partition → :meth:`on_renamed`.
    5. :meth:`on_scan_end` with stats dict.

    Returns the stats dict reported to ``on_scan_end``.
    """
    sink.on_scan_begin(
        project_root=project_root,
        commit_sha=commit_sha,
        started_at=started_at,
    )

    stats: dict[str, int] = {
        "added": 0,
        "modified": 0,
        "removed": 0,
        "moved": 0,
        "renamed": 0,
        "renamed_candidate": 0,
    }

    raw_events: list[TimelineEvent] = list(
        diff_ast_snapshots(
            prev,
            curr,
            project_root=project_root,
            timestamp=timestamp,
            author=author,
        )
    )

    edges, remaining = pair_renames(raw_events, similarity_threshold=similarity_threshold)

    # Pipe the remaining (non-consumed) events into the sink.
    for ev in remaining:
        if ev.event_type == "added":
            sink.on_added(ev)
            stats["added"] += 1
        elif ev.event_type == "modified":
            sink.on_modified(ev)
            stats["modified"] += 1
        elif ev.event_type == "removed":
            sink.on_removed(ev)
            stats["removed"] += 1
        elif ev.event_type == "moved":
            sink.on_moved(ev)
            stats["moved"] += 1
        # "renamed" is emitted via on_renamed below - never as a raw event.

    for edge in edges:
        sink.on_renamed(edge, project_root=project_root)
        if edge.is_candidate:
            stats["renamed_candidate"] += 1
        else:
            stats["renamed"] += 1

    sink.on_scan_end(
        project_root=project_root,
        commit_sha=commit_sha,
        stats=dict(stats),  # defensive copy; sinks may retain the ref
    )
    _ = finished_at  # reserved for Phase 7+ checksum use
    return stats


__all__ = ["emit_timeline"]
