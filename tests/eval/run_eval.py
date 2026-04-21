"""Eval harness adapter for the sample_repo fixture and pytest wrappers.

Canonical harness is :mod:`libs.eval.runner`. This module adds the
fixture-specific paths and a ``run_eval(retriever)`` convenience that
preserves the original signature used by existing tests and scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from libs.eval.loader import load_optional_queries_file, load_queries_file
from libs.eval.report import generate_per_query_report
from libs.eval.runner import EvalReport, QueryResult, RetrievalFn, stub_retrieve
from libs.eval.runner import run_eval as _run_eval

EVAL_DIR = Path(__file__).resolve().parent
FIXTURE_REPO = EVAL_DIR / "fixtures" / "sample_repo"
QUERIES_YAML = EVAL_DIR / "queries.yaml"
IMPACT_QUERIES_YAML = EVAL_DIR / "impact_queries.yaml"
THRESHOLDS_YAML = EVAL_DIR / "thresholds.yaml"

__all__ = [
    "EVAL_DIR",
    "FIXTURE_REPO",
    "IMPACT_QUERIES_YAML",
    "QUERIES_YAML",
    "THRESHOLDS_YAML",
    "EvalReport",
    "QueryResult",
    "RetrievalFn",
    "generate_per_query_report",
    "load_impact_queries",
    "load_queries",
    "load_thresholds",
    "run_eval",
    "stub_retrieve",
]


def load_queries() -> list[dict[str, Any]]:
    return load_queries_file(QUERIES_YAML)


def load_impact_queries() -> list[dict[str, Any]]:
    return load_optional_queries_file(IMPACT_QUERIES_YAML)


def load_thresholds() -> dict[str, Any]:
    data = yaml.safe_load(THRESHOLDS_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def run_eval(retrieve: RetrievalFn, *, repo_path: Path = FIXTURE_REPO) -> EvalReport:
    """Backward-compatible wrapper — loads fixture queries and runs the harness."""
    return _run_eval(
        retrieve,
        repo_path=repo_path,
        navigate_queries=load_queries(),
        impact_queries=load_impact_queries(),
    )


if __name__ == "__main__":
    report = run_eval(stub_retrieve)
    print(f"recall@5 files   : {report.recall_at_5_files:.3f}")
    print(f"precision@3 files: {report.precision_at_3_files:.3f}")
    print(f"recall@5 symbols : {report.recall_at_5_symbols:.3f}")
    print(f"MRR (files)      : {report.mrr_files:.3f}")
    print(f"impact_recall@5  : {report.impact_recall_at_5:.3f}")
