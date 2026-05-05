"""CI gate — pinned thresholds from baseline.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval


def test_baseline_recall_at_least_threshold() -> None:
    baseline = json.loads((Path(__file__).parent / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["resume_recall_at_5"] >= 0.90, (
        f"recall {baseline['resume_recall_at_5']} below 0.90 floor"
    )
    assert baseline["secret_leak_count"] == 0
    assert baseline["cross_user_leak_count"] == 0
    assert baseline["resume_p95_latency_ms"] <= 1500
