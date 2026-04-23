"""Timeline sink Protocol + two reference implementations.

Scanner calls sink methods inside a ``try / finally`` block so that every
``on_scan_begin`` has a matching ``on_scan_end`` even when diffing raises.

Two shipped implementations:

* :class:`SqliteTimelineSink` — persistent store-backed sink (default).
* :class:`MemoryTimelineSink` — in-process list, for unit tests and dry-runs.

Third-party sinks register via ``TimelineConfig.sink_plugins`` (Phase 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from libs.symbol_timeline.rename_detect import RenameEdge
from libs.symbol_timeline.store import (
    RenameEdgeRow,
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
    append_rename_edge,
)
from libs.telemetry.timeline_metrics import record_event, record_sink_error


@runtime_checkable
class TimelineSink(Protocol):
    """Consumer of timeline events emitted by the scanner (spec FR-003).

    Lifecycle (per scan):

    .. code-block:: text

        on_scan_begin
            ( on_added | on_modified | on_removed | on_moved | on_renamed ) *
        on_scan_end                                       (in ``finally``)

    Implementations MUST be idempotent per ``(event.symbol_id, event.commit_sha)``
    — retried scans must not duplicate rows. Exceptions inside ``on_*`` are
    caught by the scanner and counted in ``symbol_timeline_sink_errors_total``
    (Phase 8 metrics); three consecutive failures auto-disable the sink.
    """

    def on_scan_begin(
        self,
        *,
        project_root: str,
        commit_sha: str | None,
        started_at: float,
    ) -> None: ...

    def on_scan_end(
        self,
        *,
        project_root: str,
        commit_sha: str | None,
        stats: Mapping[str, int],
    ) -> None: ...

    def on_added(self, event: TimelineEvent) -> None: ...

    def on_modified(self, event: TimelineEvent) -> None: ...

    def on_removed(self, event: TimelineEvent) -> None: ...

    def on_moved(self, event: TimelineEvent) -> None: ...

    def on_renamed(self, edge: RenameEdge, *, project_root: str) -> None: ...


# ---------------------------------------------------------------------------
# Reference implementations
# ---------------------------------------------------------------------------


@dataclass
class MemoryTimelineSink:
    """In-memory sink collecting every event for inspection.

    Unit tests assert against ``events``, ``edges``, ``begins``, ``ends``.
    Not thread-safe — tests run serially.
    """

    events: list[TimelineEvent] = field(default_factory=list)
    edges: list[RenameEdge] = field(default_factory=list)
    begins: list[tuple[str, str | None, float]] = field(default_factory=list)
    ends: list[tuple[str, str | None, Mapping[str, int]]] = field(default_factory=list)

    def on_scan_begin(
        self,
        *,
        project_root: str,
        commit_sha: str | None,
        started_at: float,
    ) -> None:
        self.begins.append((project_root, commit_sha, started_at))

    def on_scan_end(
        self,
        *,
        project_root: str,
        commit_sha: str | None,
        stats: Mapping[str, int],
    ) -> None:
        # Snapshot the stats so later mutations in caller don't leak in.
        self.ends.append((project_root, commit_sha, dict(stats)))

    def on_added(self, event: TimelineEvent) -> None:
        self.events.append(event)

    def on_modified(self, event: TimelineEvent) -> None:
        self.events.append(event)

    def on_removed(self, event: TimelineEvent) -> None:
        self.events.append(event)

    def on_moved(self, event: TimelineEvent) -> None:
        self.events.append(event)

    def on_renamed(self, edge: RenameEdge, *, project_root: str) -> None:
        self.edges.append(edge)

    # Helpers for tests.

    def events_of_type(self, event_type: str) -> list[TimelineEvent]:
        return [e for e in self.events if e.event_type == event_type]


@dataclass
class SqliteTimelineSink:
    """Persistent sink backed by :class:`SymbolTimelineStore`.

    Call ``migrate()`` once (or let the caller do it) before first use.
    Retention pruning is delegated to ``append_event`` via ``retention_days``.

    Every ``on_*`` callback increments
    ``symbol_timeline_events_total{event_type,project}`` on success and
    ``symbol_timeline_sink_errors_total{sink="sqlite",stage=...}`` on
    failure. Exceptions are re-raised so the scanner can decide whether to
    continue or abort the run.
    """

    store: SymbolTimelineStore
    retention_days: int | None = None
    _sink_name: str = "sqlite"

    def on_scan_begin(
        self,
        *,
        project_root: str,
        commit_sha: str | None,
        started_at: float,
    ) -> None:
        # No-op today. Phase 8 may stamp a scan-start marker for observability.
        _ = (project_root, commit_sha, started_at)

    def on_scan_end(
        self,
        *,
        project_root: str,
        commit_sha: str | None,
        stats: Mapping[str, int],
    ) -> None:
        # No-op today. Phase 7 adds a scan-end marker for reconcile replay.
        _ = (project_root, commit_sha, stats)

    def _append(self, event: TimelineEvent, *, stage: str) -> None:
        try:
            append_event(self.store, event=event, retention_days=self.retention_days)
        except Exception:
            record_sink_error(self._sink_name, stage)
            raise
        record_event(event.event_type, event.project_root)

    def on_added(self, event: TimelineEvent) -> None:
        self._append(event, stage="on_added")

    def on_modified(self, event: TimelineEvent) -> None:
        self._append(event, stage="on_modified")

    def on_removed(self, event: TimelineEvent) -> None:
        self._append(event, stage="on_removed")

    def on_moved(self, event: TimelineEvent) -> None:
        self._append(event, stage="on_moved")

    def on_renamed(self, edge: RenameEdge, *, project_root: str) -> None:
        try:
            append_rename_edge(
                self.store,
                edge=RenameEdgeRow(
                    project_root=project_root,
                    old_symbol_id=edge.old_symbol_id,
                    new_symbol_id=edge.new_symbol_id,
                    commit_sha=edge.commit_sha,
                    timestamp=edge.timestamp,
                    confidence=edge.confidence,
                    is_candidate=edge.is_candidate,
                ),
            )
        except Exception:
            record_sink_error(self._sink_name, "on_renamed")
            raise
