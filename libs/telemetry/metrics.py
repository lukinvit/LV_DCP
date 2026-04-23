"""Minimal Prometheus-compatible metrics registry (stdlib-only).

Why roll our own: LV_DCP is a local-first developer tool. Adding
``prometheus_client`` would pull a dependency tree we don't otherwise
need, and we only emit a handful of metrics from a handful of code
paths. This 120-line module covers ``Counter`` + ``Histogram`` (the
two shapes the spec cares about), a central ``REGISTRY``, and a
``render_text()`` that speaks the Prometheus 0.0.4 exposition format.

Label semantics:

* Each metric has a fixed label schema (``labelnames``). The same set
  of label *names* is used for every child; label *values* select the
  child series. This matches prometheus_client's contract without
  importing it.
* ``.labels(**kwargs)`` returns a ``_Child`` you can call ``.inc()`` /
  ``.observe()`` on. Calls are thread-safe via a single registry lock.

Spec: specs/010-feature-timeline-index/plan.md Layer 5.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable


_DEFAULT_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    math.inf,
)


@dataclass
class _CounterChild:
    _value: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            msg = "Counter.inc amount must be non-negative"
            raise ValueError(msg)
        self._value += amount

    def value(self) -> float:
        return self._value


@dataclass
class _HistogramChild:
    buckets: tuple[float, ...]
    _count: int = 0
    _sum: float = 0.0
    _bucket_counts: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self._bucket_counts:
            self._bucket_counts = [0] * len(self.buckets)

    def observe(self, amount: float) -> None:
        self._count += 1
        self._sum += amount
        for i, upper in enumerate(self.buckets):
            if amount <= upper:
                self._bucket_counts[i] += 1

    def snapshot(self) -> tuple[int, float, list[int]]:
        return self._count, self._sum, list(self._bucket_counts)


class _Metric:
    def __init__(self, name: str, help_text: str, labelnames: tuple[str, ...]) -> None:
        self.name = name
        self.help_text = help_text
        self.labelnames = labelnames
        self._lock = threading.Lock()

    def _key(self, label_values: tuple[str, ...]) -> tuple[str, ...]:
        if len(label_values) != len(self.labelnames):
            msg = (
                f"metric {self.name}: expected {len(self.labelnames)} labels, "
                f"got {len(label_values)}"
            )
            raise ValueError(msg)
        return label_values


class Counter(_Metric):
    """Monotonic counter with labeled children."""

    def __init__(
        self,
        name: str,
        help_text: str,
        labelnames: Iterable[str] = (),
    ) -> None:
        super().__init__(name, help_text, tuple(labelnames))
        self._children: dict[tuple[str, ...], _CounterChild] = {}

    def labels(self, **kwargs: str) -> _CounterChild:
        values = tuple(kwargs[name] for name in self.labelnames)
        with self._lock:
            child = self._children.get(values)
            if child is None:
                child = _CounterChild()
                self._children[values] = child
        return child

    def inc(self, amount: float = 1.0) -> None:
        """Label-less increment — valid only when ``labelnames=()``."""
        if self.labelnames:
            msg = f"counter {self.name} has labels; use .labels(...).inc()"
            raise ValueError(msg)
        self.labels().inc(amount)

    def value(self) -> float:
        if self.labelnames:
            msg = f"counter {self.name} has labels; use .labels(...).value()"
            raise ValueError(msg)
        return self.labels().value()

    def snapshot(self) -> dict[tuple[str, ...], float]:
        with self._lock:
            return {k: v._value for k, v in self._children.items()}


class Histogram(_Metric):
    """Bucketed histogram with labeled children and a fixed bucket schedule."""

    def __init__(
        self,
        name: str,
        help_text: str,
        labelnames: Iterable[str] = (),
        buckets: Iterable[float] = _DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, tuple(labelnames))
        self.buckets = tuple(buckets)
        if math.inf not in self.buckets:
            self.buckets = (*self.buckets, math.inf)
        self._children: dict[tuple[str, ...], _HistogramChild] = {}

    def labels(self, **kwargs: str) -> _HistogramChild:
        values = tuple(kwargs[name] for name in self.labelnames)
        with self._lock:
            child = self._children.get(values)
            if child is None:
                child = _HistogramChild(buckets=self.buckets)
                self._children[values] = child
        return child

    def observe(self, amount: float) -> None:
        if self.labelnames:
            msg = f"histogram {self.name} has labels; use .labels(...).observe()"
            raise ValueError(msg)
        self.labels().observe(amount)

    def snapshot(
        self,
    ) -> dict[tuple[str, ...], tuple[int, float, list[int]]]:
        with self._lock:
            return {k: v.snapshot() for k, v in self._children.items()}


@dataclass
class MetricsRegistry:
    """Central registry of named metrics — rendered as Prometheus text."""

    metrics: dict[str, _Metric] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def register(self, metric: _Metric) -> _Metric:
        with self._lock:
            existing = self.metrics.get(metric.name)
            if existing is not None:
                return existing
            self.metrics[metric.name] = metric
        return metric

    def counter(self, name: str, help_text: str, labelnames: Iterable[str] = ()) -> Counter:
        return self.register(Counter(name, help_text, labelnames))  # type: ignore[return-value]

    def histogram(
        self,
        name: str,
        help_text: str,
        labelnames: Iterable[str] = (),
        buckets: Iterable[float] = _DEFAULT_BUCKETS,
    ) -> Histogram:
        return self.register(  # type: ignore[return-value]
            Histogram(name, help_text, labelnames, buckets)
        )

    def reset(self) -> None:
        """Drop every metric — for test isolation only."""
        with self._lock:
            self.metrics.clear()


def _escape_label_value(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not names:
        return ""
    parts = [f'{n}="{_escape_label_value(v)}"' for n, v in zip(names, values, strict=True)]
    return "{" + ",".join(parts) + "}"


def render_text(registry: MetricsRegistry) -> str:
    """Serialize ``registry`` as Prometheus 0.0.4 exposition text."""
    lines: list[str] = []
    for metric in registry.metrics.values():
        if isinstance(metric, Counter):
            lines.append(f"# HELP {metric.name} {metric.help_text}")
            lines.append(f"# TYPE {metric.name} counter")
            for labels, value in metric.snapshot().items():
                lines.append(f"{metric.name}{_format_labels(metric.labelnames, labels)} {value}")
        elif isinstance(metric, Histogram):
            lines.append(f"# HELP {metric.name} {metric.help_text}")
            lines.append(f"# TYPE {metric.name} histogram")
            for labels, (count, total, bucket_counts) in metric.snapshot().items():
                base = _format_labels(metric.labelnames, labels)
                for upper, bc in zip(metric.buckets, bucket_counts, strict=True):
                    le = "+Inf" if math.isinf(upper) else repr(upper)
                    extras = f',le="{le}"' if base else f'{{le="{le}"}}'
                    payload = base[:-1] + extras + "}" if base else extras
                    lines.append(f"{metric.name}_bucket{payload} {bc}")
                lines.append(f"{metric.name}_sum{base} {total}")
                lines.append(f"{metric.name}_count{base} {count}")
    return "\n".join(lines) + ("\n" if lines else "")


REGISTRY: Final[MetricsRegistry] = MetricsRegistry()
