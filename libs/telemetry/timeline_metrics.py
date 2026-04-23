"""Timeline-specific Prometheus metrics (spec-010 T038, plan.md Layer 5).

All five metrics share the global :data:`libs.telemetry.metrics.REGISTRY`
singleton. They are registered eagerly on import so that
``render_text(REGISTRY)`` always emits the full ``# HELP`` / ``# TYPE``
preamble even before any observation — Prometheus scrapes expect
metric metadata to be stable across scrapes.

Metrics (names & shapes are part of the spec's observability contract):

1. ``symbol_timeline_events_total`` — Counter, labels ``(event_type,
   project)``. Incremented in :class:`libs.symbol_timeline.sinks.
   SqliteTimelineSink` for every event written.
2. ``symbol_timeline_query_latency_seconds`` — Histogram, label
   ``(tool,)``. Observed around :func:`libs.symbol_timeline.query.
   find_removed_since` and :func:`diff`, and around the MCP tool
   dispatcher.
3. ``symbol_timeline_snapshot_build_seconds`` — Histogram, no labels.
   Observed around :func:`libs.symbol_timeline.snapshot.
   build_release_snapshot`.
4. ``symbol_timeline_reconcile_orphaned_total`` — Counter, label
   ``(project,)``. Incremented by :func:`libs.symbol_timeline.reconcile.
   reconcile` with ``report.orphaned_newly_flagged``.
5. ``symbol_timeline_sink_errors_total`` — Counter, labels ``(sink,
   stage)``. Incremented by the sink wrapper when an ``on_*`` callback
   raises; three consecutive increments per sink disable it (spec §FR-003).

The instrumentation helpers (``observe_query_latency``, ``time_block``)
are ``contextlib`` context managers so call sites stay readable:

.. code-block:: python

    with observe_query_latency("removed_since"):
        result = find_removed_since(...)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from libs.telemetry.metrics import REGISTRY, Counter, Histogram

if TYPE_CHECKING:
    from collections.abc import Iterator


# Histogram bucket schedule for query / build latency (seconds).
# Spec budget: p95 query < 150 ms (plan.md SC-002) — buckets zoom in below
# that threshold so we get tight resolution where the SLO lives.
_LATENCY_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.15,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)


events_total: Final[Counter] = REGISTRY.counter(
    "symbol_timeline_events_total",
    "Total timeline events written to persistent sinks, by event_type.",
    labelnames=("event_type", "project"),
)

query_latency_seconds: Final[Histogram] = REGISTRY.histogram(
    "symbol_timeline_query_latency_seconds",
    "Latency of timeline read-side queries in seconds.",
    labelnames=("tool",),
    buckets=_LATENCY_BUCKETS,
)

snapshot_build_seconds: Final[Histogram] = REGISTRY.histogram(
    "symbol_timeline_snapshot_build_seconds",
    "Latency of release-snapshot fingerprinting in seconds.",
    buckets=_LATENCY_BUCKETS,
)

reconcile_orphaned_total: Final[Counter] = REGISTRY.counter(
    "symbol_timeline_reconcile_orphaned_total",
    "Total events newly flagged as orphaned by reconcile runs.",
    labelnames=("project",),
)

sink_errors_total: Final[Counter] = REGISTRY.counter(
    "symbol_timeline_sink_errors_total",
    "Total exceptions raised by timeline sink callbacks.",
    labelnames=("sink", "stage"),
)


# ---------------------------------------------------------------------------
# Instrumentation helpers — keep call sites concise.
# ---------------------------------------------------------------------------


@contextmanager
def observe_query_latency(tool: str) -> Iterator[None]:
    """Observe elapsed seconds in ``query_latency_seconds{tool=...}``.

    Uses ``time.perf_counter`` so we measure wall-clock elapsed, not CPU
    time — timeline queries are I/O-dominated against SQLite.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        query_latency_seconds.labels(tool=tool).observe(time.perf_counter() - start)


@contextmanager
def observe_snapshot_build() -> Iterator[None]:
    """Observe elapsed seconds in ``snapshot_build_seconds``."""
    start = time.perf_counter()
    try:
        yield
    finally:
        snapshot_build_seconds.observe(time.perf_counter() - start)


def record_event(event_type: str, project: str) -> None:
    """Bump ``symbol_timeline_events_total`` for one written event."""
    events_total.labels(event_type=event_type, project=project).inc()


def record_reconcile_orphans(project: str, newly_flagged: int) -> None:
    """Bump ``symbol_timeline_reconcile_orphaned_total`` by ``newly_flagged``."""
    if newly_flagged <= 0:
        return
    reconcile_orphaned_total.labels(project=project).inc(float(newly_flagged))


def record_sink_error(sink: str, stage: str) -> None:
    """Bump ``symbol_timeline_sink_errors_total`` for one exception."""
    sink_errors_total.labels(sink=sink, stage=stage).inc()


__all__ = [
    "events_total",
    "observe_query_latency",
    "observe_snapshot_build",
    "query_latency_seconds",
    "reconcile_orphaned_total",
    "record_event",
    "record_reconcile_orphans",
    "record_sink_error",
    "sink_errors_total",
    "snapshot_build_seconds",
]
