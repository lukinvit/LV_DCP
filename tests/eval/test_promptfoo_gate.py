"""Simulation of the promptfoo regression gate (see specs/006, T033).

We don't exec ``npx promptfoo`` in-process — it's a node subprocess that
would flake in CI without Node. Instead we replicate the *math* the
promptfoo.config.yaml asserts and prove that:

1. The committed baseline passes the gate (no regression against itself).
2. A degraded retriever (returns wrong files) trips the 2pp threshold on
   every metric.

If the gate math in promptfoo.config.yaml ever drifts from this file,
that's a red flag — the numbers here and the JS there must agree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from libs.eval.history import report_to_dict
from libs.eval.runner import EvalReport, run_eval

BASELINE_PATH = Path(__file__).resolve().parent / "baselines" / "main.json"
TOLERANCE = 0.02  # 2 pp — mirrors tests/eval/promptfoo.config.yaml

METRICS = (
    "recall_at_5_files",
    "precision_at_3_files",
    "recall_at_5_symbols",
    "mrr_files",
    "impact_recall_at_5",
)


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _regression_violations(
    report: dict[str, Any], baseline: dict[str, Any]
) -> list[str]:
    """Replicate the per-metric assertion in promptfoo.config.yaml."""
    violations: list[str] = []
    for name in METRICS:
        if report[name] + TOLERANCE < baseline[name]:
            violations.append(
                f"{name}: {report[name]:.3f} vs baseline {baseline[name]:.3f}"
            )
    return violations


def test_promptfoo_baseline_is_loadable_and_sane() -> None:
    data = _load_baseline()
    assert data["schema_version"] == 1
    for name in METRICS:
        v = data[name]
        assert isinstance(v, (int, float))
        assert 0.0 <= v <= 1.0, f"{name} out of [0, 1]: {v}"


def test_promptfoo_gate_passes_on_unchanged_baseline() -> None:
    baseline = _load_baseline()
    # Echo the baseline back — identity must pass the gate.
    assert _regression_violations(baseline, baseline) == []


def test_promptfoo_gate_catches_uniform_regression() -> None:
    baseline = _load_baseline()
    # Knock every metric down by 3 pp — more than TOLERANCE.
    degraded = dict(baseline)
    for name in METRICS:
        degraded[name] = max(0.0, baseline[name] - 0.03)

    violations = _regression_violations(degraded, baseline)
    assert len(violations) == len(METRICS), (
        f"expected all {len(METRICS)} metrics to regress, got {violations}"
    )


def test_promptfoo_gate_tolerates_small_drop() -> None:
    baseline = _load_baseline()
    # Drop by 1 pp — below TOLERANCE (2 pp). Must NOT trip the gate.
    nearly = dict(baseline)
    for name in METRICS:
        nearly[name] = max(0.0, baseline[name] - 0.01)

    assert _regression_violations(nearly, baseline) == []


def test_promptfoo_gate_on_fake_bad_retriever(tmp_path: Path) -> None:
    """End-to-end: a retriever that returns garbage produces a report
    that fails the gate.

    Uses the real sample_repo + real queries to build the degraded report —
    this catches drift between the harness wiring and the config math.
    """
    from tests.eval.run_eval import FIXTURE_REPO, load_impact_queries, load_queries

    # Retriever that returns one irrelevant file + no symbols for everything.
    def bad_retrieve(
        _query: str, _mode: str, _repo: Path
    ) -> tuple[list[str], list[str]]:
        return ["does/not/exist.py"], []

    report: EvalReport = run_eval(
        bad_retrieve,
        repo_path=FIXTURE_REPO,
        navigate_queries=load_queries(),
        impact_queries=load_impact_queries(),
    )
    # Sanity: bad retriever must score zero on recall@5 files.
    assert report.recall_at_5_files == pytest.approx(0.0)

    baseline = _load_baseline()
    violations = _regression_violations(report_to_dict(report), baseline)
    assert violations, "bad retriever must trip at least one gate metric"


def test_promptfoo_config_mentions_expected_metrics() -> None:
    """Guard against silent drift between this test's METRICS and the JS config."""
    config = (BASELINE_PATH.parent.parent / "promptfoo.config.yaml").read_text(
        encoding="utf-8"
    )
    for name in METRICS:
        assert name in config, f"metric {name!r} not referenced in promptfoo.config.yaml"


def test_promptfoo_config_has_matching_tolerance() -> None:
    config = (BASELINE_PATH.parent.parent / "promptfoo.config.yaml").read_text(
        encoding="utf-8"
    )
    # We hard-code TOL = 0.02 in five places in the config. At minimum two
    # occurrences must match (defensive against reformatting).
    assert config.count(f"{TOLERANCE}") >= 2, (
        f"tolerance {TOLERANCE} not found in promptfoo.config.yaml — math drift"
    )
