"""Polyglot eval harness — tests retrieval on Go + TypeScript + mixed projects.

Requires real projects to be scanned. Skips gracefully if projects not available.
"""
from __future__ import annotations

import pytest

from tests.eval.run_polyglot_eval import PolyglotReport, run_polyglot_eval

pytestmark = pytest.mark.eval

# Thresholds for polyglot retrieval
OVERALL_RECALL_THRESHOLD = 0.50
PER_PROJECT_THRESHOLDS = {
    "GoTS_Project": 0.40,  # Mixed Go+TS, harder
    "PythonTS_Project": 0.50,
}


def test_polyglot_eval_meets_thresholds() -> None:
    report: PolyglotReport = run_polyglot_eval()

    if not report.results:
        pytest.skip("No polyglot projects available for eval")

    # Print per-query results for debugging
    for r in report.results:
        status = "PASS" if r.recall_5 >= 0.5 else "MISS"
        print(f"  [{status}] {r.query_id}: recall@5={r.recall_5:.2f} "
              f"expected={r.expected_files} got={r.retrieved_files[:3]}")

    print(f"\nPer-project recall: {report.per_project_recall}")
    print(f"Overall recall@5: {report.overall_recall:.3f}")

    failures: list[str] = []

    if report.overall_recall < OVERALL_RECALL_THRESHOLD:
        failures.append(
            f"overall recall@5 = {report.overall_recall:.3f} "
            f"< threshold {OVERALL_RECALL_THRESHOLD:.3f}"
        )

    for proj, threshold in PER_PROJECT_THRESHOLDS.items():
        actual = report.per_project_recall.get(proj, 0.0)
        if actual < threshold:
            failures.append(
                f"{proj} recall@5 = {actual:.3f} < threshold {threshold:.3f}"
            )

    if failures:
        msg = "Polyglot eval below thresholds:\n  - " + "\n  - ".join(failures)
        pytest.fail(msg)
