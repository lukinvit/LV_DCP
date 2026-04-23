"""Registry primitives — Counter, Histogram, render_text (spec-010 T038)."""

from __future__ import annotations

import math

import pytest
from libs.telemetry.metrics import (
    Counter,
    Histogram,
    MetricsRegistry,
    render_text,
)


def test_counter_without_labels_increments() -> None:
    reg = MetricsRegistry()
    c = reg.counter("ops_total", "total ops")
    c.inc()
    c.inc(2.5)
    assert c.value() == pytest.approx(3.5)


def test_counter_rejects_negative_increments() -> None:
    reg = MetricsRegistry()
    c = reg.counter("ops_total", "total ops")
    with pytest.raises(ValueError, match="non-negative"):
        c.inc(-1)


def test_labeled_counter_children_are_independent() -> None:
    reg = MetricsRegistry()
    c = reg.counter("events_total", "events", labelnames=("type",))
    c.labels(type="added").inc()
    c.labels(type="added").inc()
    c.labels(type="removed").inc()
    snap = c.snapshot()
    assert snap[("added",)] == 2
    assert snap[("removed",)] == 1


def test_counter_without_labels_disallows_labels_call() -> None:
    reg = MetricsRegistry()
    c = reg.counter("events_total", "events", labelnames=("type",))
    with pytest.raises(ValueError, match="has labels"):
        c.inc()


def test_counter_labels_require_matching_arity() -> None:
    reg = MetricsRegistry()
    c = reg.counter("events_total", "events", labelnames=("type", "project"))
    with pytest.raises((KeyError, ValueError)):
        c.labels(type="added")  # missing "project"


def test_histogram_default_buckets_contain_inf() -> None:
    reg = MetricsRegistry()
    h = reg.histogram("latency_seconds", "query latency")
    assert math.inf in h.buckets


def test_histogram_observes_and_reports_counts() -> None:
    reg = MetricsRegistry()
    h = reg.histogram("latency_seconds", "query latency", buckets=(0.1, 0.5, 1.0))
    h.observe(0.05)
    h.observe(0.3)
    h.observe(2.0)
    ((_labels, (count, total, bucket_counts)),) = h.snapshot().items()
    assert count == 3
    assert total == pytest.approx(2.35)
    # 0.05 ≤ 0.1 ≤ 0.5 ≤ 1.0 ≤ +Inf  → [1, 1, 1, 1]
    # 0.3 ≤ 0.5 ≤ 1.0 ≤ +Inf          → add to buckets ≥ 0.5
    # 2.0 > 1.0 but ≤ +Inf            → only +Inf
    # buckets as configured: (0.1, 0.5, 1.0, +Inf)
    assert bucket_counts == [1, 2, 2, 3]


def test_histogram_labeled_children() -> None:
    reg = MetricsRegistry()
    h = reg.histogram(
        "latency_seconds",
        "query latency",
        labelnames=("tool",),
        buckets=(0.5,),
    )
    h.labels(tool="diff").observe(0.1)
    h.labels(tool="diff").observe(0.2)
    h.labels(tool="removed_since").observe(1.0)
    snap = h.snapshot()
    assert snap[("diff",)][0] == 2
    assert snap[("removed_since",)][0] == 1


def test_render_text_counter_output_is_prometheus_shaped() -> None:
    reg = MetricsRegistry()
    c = reg.counter("ops_total", "total ops")
    c.inc(3)
    out = render_text(reg)
    assert "# HELP ops_total total ops" in out
    assert "# TYPE ops_total counter" in out
    assert "ops_total 3" in out
    assert out.endswith("\n")


def test_render_text_histogram_emits_bucket_sum_count() -> None:
    reg = MetricsRegistry()
    h = reg.histogram(
        "latency_seconds",
        "query latency",
        labelnames=("tool",),
        buckets=(0.1, 1.0),
    )
    h.labels(tool="diff").observe(0.05)
    h.labels(tool="diff").observe(0.5)
    out = render_text(reg)
    assert "# TYPE latency_seconds histogram" in out
    assert 'latency_seconds_bucket{tool="diff",le="0.1"} 1' in out
    assert 'latency_seconds_bucket{tool="diff",le="1.0"} 2' in out
    assert 'latency_seconds_bucket{tool="diff",le="+Inf"} 2' in out
    assert 'latency_seconds_sum{tool="diff"} 0.55' in out
    assert 'latency_seconds_count{tool="diff"} 2' in out


def test_registry_register_is_idempotent_on_name() -> None:
    reg = MetricsRegistry()
    a = reg.counter("ops_total", "v1")
    b = reg.counter("ops_total", "v2")
    assert a is b  # second registration returns the existing metric


def test_registry_reset_empties_everything() -> None:
    reg = MetricsRegistry()
    reg.counter("a_total", "a")
    reg.histogram("b_seconds", "b")
    reg.reset()
    assert reg.metrics == {}


def test_label_value_escaping_handles_special_chars() -> None:
    reg = MetricsRegistry()
    c = reg.counter("ops_total", "ops", labelnames=("path",))
    c.labels(path='a"b\nc\\d').inc()
    out = render_text(reg)
    # Escaped form: backslash first, then quote, then newline.
    assert r'path="a\"b\nc\\d"' in out


def test_empty_registry_render_is_empty_string() -> None:
    reg = MetricsRegistry()
    assert render_text(reg) == ""


def test_counter_class_direct_use() -> None:
    """Tests that Counter can be instantiated without a registry."""
    c = Counter("direct_total", "direct")
    c.inc()
    assert c.value() == 1.0


def test_histogram_class_direct_use() -> None:
    h = Histogram("direct_seconds", "direct", buckets=(1.0,))
    h.observe(0.5)
    ((_, (count, total, _)),) = h.snapshot().items()
    assert count == 1
    assert total == 0.5
