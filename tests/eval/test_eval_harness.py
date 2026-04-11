"""Pytest wrapper around the eval harness.

Applies the active-phase thresholds from thresholds.yaml and fails if any
metric falls below its threshold. See ADR-002.
"""

from __future__ import annotations

import pytest

from tests.eval.run_eval import EvalReport, RetrievalFn, load_thresholds, run_eval

pytestmark = pytest.mark.eval


def _active_thresholds() -> dict[str, float]:
    data = load_thresholds()
    phase = str(data["active_phase"])
    thresholds = data["phases"][phase]
    return {
        "recall_at_5_files": float(thresholds["recall_at_5_files"]),
        "precision_at_3_files": float(thresholds["precision_at_3_files"]),
        "recall_at_5_symbols": float(thresholds["recall_at_5_symbols"]),
        "impact_recall_at_5": float(thresholds.get("impact_recall_at_5", 0.0)),
    }


def _current_retrieve() -> RetrievalFn:
    """Phase 1+: use the real retrieval pipeline via the adapter."""
    from tests.eval.retrieval_adapter import retrieve_for_eval

    return retrieve_for_eval


def test_eval_harness_meets_thresholds() -> None:
    thresholds = _active_thresholds()
    report: EvalReport = run_eval(_current_retrieve())

    failures: list[str] = []
    if report.recall_at_5_files < thresholds["recall_at_5_files"]:
        failures.append(
            f"recall@5 files = {report.recall_at_5_files:.3f} "
            f"< threshold {thresholds['recall_at_5_files']:.3f}"
        )
    if report.precision_at_3_files < thresholds["precision_at_3_files"]:
        failures.append(
            f"precision@3 files = {report.precision_at_3_files:.3f} "
            f"< threshold {thresholds['precision_at_3_files']:.3f}"
        )
    if report.recall_at_5_symbols < thresholds["recall_at_5_symbols"]:
        failures.append(
            f"recall@5 symbols = {report.recall_at_5_symbols:.3f} "
            f"< threshold {thresholds['recall_at_5_symbols']:.3f}"
        )
    if report.impact_recall_at_5 < thresholds["impact_recall_at_5"]:
        failures.append(
            f"impact_recall@5 = {report.impact_recall_at_5:.3f} "
            f"< threshold {thresholds['impact_recall_at_5']:.3f}"
        )

    if failures:
        msg = "Eval harness below thresholds:\n  - " + "\n  - ".join(failures)
        pytest.fail(msg)
