"""Timeline-specific metrics + helper instrumentation (spec-010 T038)."""

from __future__ import annotations

import time

import pytest
from libs.telemetry import timeline_metrics as tm


def test_five_metrics_are_registered_on_import() -> None:
    """All five plan.md Layer 5 metrics must be present on REGISTRY."""
    from libs.telemetry.metrics import REGISTRY

    names = set(REGISTRY.metrics.keys())
    assert "symbol_timeline_events_total" in names
    assert "symbol_timeline_query_latency_seconds" in names
    assert "symbol_timeline_snapshot_build_seconds" in names
    assert "symbol_timeline_reconcile_orphaned_total" in names
    assert "symbol_timeline_sink_errors_total" in names


def test_record_event_increments_counter() -> None:
    before = tm.events_total.labels(event_type="added", project="/tmp/p1").value()
    tm.record_event("added", "/tmp/p1")
    tm.record_event("added", "/tmp/p1")
    after = tm.events_total.labels(event_type="added", project="/tmp/p1").value()
    assert after - before == 2


def test_record_event_isolates_by_labels() -> None:
    tm.record_event("added", "/tmp/a")
    tm.record_event("removed", "/tmp/b")
    a_added = tm.events_total.labels(event_type="added", project="/tmp/a").value()
    b_removed = tm.events_total.labels(event_type="removed", project="/tmp/b").value()
    assert a_added >= 1
    assert b_removed >= 1
    # No cross-contamination.
    assert (
        tm.events_total.labels(event_type="added", project="/tmp/b").value() != a_added
        or b_removed == 0
    )


def test_record_reconcile_orphans_skips_zero_and_negative() -> None:
    before = tm.reconcile_orphaned_total.labels(project="/tmp/z").value()
    tm.record_reconcile_orphans("/tmp/z", 0)
    tm.record_reconcile_orphans("/tmp/z", -3)
    after = tm.reconcile_orphaned_total.labels(project="/tmp/z").value()
    assert after == before


def test_record_reconcile_orphans_adds_count() -> None:
    before = tm.reconcile_orphaned_total.labels(project="/tmp/orphan").value()
    tm.record_reconcile_orphans("/tmp/orphan", 4)
    after = tm.reconcile_orphaned_total.labels(project="/tmp/orphan").value()
    assert after - before == 4


def test_record_sink_error_increments() -> None:
    before = tm.sink_errors_total.labels(sink="sqlite", stage="on_added").value()
    tm.record_sink_error("sqlite", "on_added")
    after = tm.sink_errors_total.labels(sink="sqlite", stage="on_added").value()
    assert after - before == 1


def test_observe_query_latency_records_bucket() -> None:
    with tm.observe_query_latency("unit_test_tool"):
        time.sleep(0.001)
    snap = tm.query_latency_seconds.snapshot()
    assert ("unit_test_tool",) in snap
    count, total, _ = snap[("unit_test_tool",)]
    assert count >= 1
    assert total > 0


def test_observe_query_latency_is_reentrant_safe() -> None:
    """Nested blocks must each observe their own elapsed."""
    with tm.observe_query_latency("outer_tool"), tm.observe_query_latency("inner_tool"):
        pass
    outer = tm.query_latency_seconds.snapshot().get(("outer_tool",))
    inner = tm.query_latency_seconds.snapshot().get(("inner_tool",))
    assert outer is not None
    assert inner is not None
    assert outer[0] >= 1
    assert inner[0] >= 1


def test_observe_snapshot_build_records_sample() -> None:
    before_count = tm.snapshot_build_seconds.snapshot().get((), (0, 0.0, []))[0]
    with tm.observe_snapshot_build():
        pass
    after_count = tm.snapshot_build_seconds.snapshot().get((), (0, 0.0, []))[0]
    assert after_count == before_count + 1


def test_observe_query_latency_records_on_exception() -> None:
    """The context manager must still observe when the block raises."""
    before = tm.query_latency_seconds.snapshot().get(("raising_tool",), (0, 0.0, []))[0]
    with pytest.raises(RuntimeError), tm.observe_query_latency("raising_tool"):
        raise RuntimeError("boom")
    after = tm.query_latency_seconds.snapshot().get(("raising_tool",), (0, 0.0, []))[0]
    assert after == before + 1
