"""Lightweight telemetry primitives for LV_DCP — spec-010 T038.

Stdlib-only metrics: ``Counter``, ``Histogram``, plus a central
:data:`REGISTRY` that renders Prometheus exposition format on demand.
We intentionally avoid pulling ``prometheus_client`` — LV_DCP is a
local-first tool and the full client is heavier than we need. When a
real Prometheus scrape is wired up later, ``render_text()`` is the
integration point.

Submodules:

* :mod:`libs.telemetry.metrics` — registry primitives.
* :mod:`libs.telemetry.timeline_metrics` — the five symbol_timeline
  metrics from plan.md Layer 5, plus instrumentation helpers.
"""

from libs.telemetry.metrics import (
    REGISTRY,
    Counter,
    Histogram,
    MetricsRegistry,
    render_text,
)

__all__ = [
    "REGISTRY",
    "Counter",
    "Histogram",
    "MetricsRegistry",
    "render_text",
]
