"""Smoke test for the Aider repo-map baseline."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "sample_repo"


@pytest.mark.skipif(not FIXTURE.exists(), reason="sample_repo fixture missing")
def test_aider_baseline_returns_ranked_files() -> None:
    from tests.eval.baselines.aider_repomap import aider_baseline_retrieve

    files, symbols = aider_baseline_retrieve(
        "session factory database connection",
        mode="navigate",
        repo=FIXTURE,
    )
    assert isinstance(files, list)
    assert all(isinstance(f, str) for f in files)
    assert len(files) <= 10
    assert all(isinstance(s, str) for s in symbols)
    # Fixture is small — baseline must produce at least one candidate.
    assert files


@pytest.mark.skipif(not FIXTURE.exists(), reason="sample_repo fixture missing")
def test_aider_baseline_personalization_biases_toward_query_terms() -> None:
    from tests.eval.baselines.aider_repomap import aider_baseline_retrieve

    session_results, _ = aider_baseline_retrieve("session", "navigate", FIXTURE)
    worker_results, _ = aider_baseline_retrieve("worker", "navigate", FIXTURE)
    # Two different queries should surface different top files on a small fixture.
    assert session_results != worker_results
