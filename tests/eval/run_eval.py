"""Eval harness runner.

Loads queries.yaml, invokes a retrieval callable against the fixture repo,
and returns aggregated metrics. No pytest dependency here — this is importable
from scripts and from the pytest wrapper in test_eval_harness.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.eval.metrics import mean_reciprocal_rank, precision_at_k, recall_at_k

EVAL_DIR = Path(__file__).resolve().parent
FIXTURE_REPO = EVAL_DIR / "fixtures" / "sample_repo"
QUERIES_YAML = EVAL_DIR / "queries.yaml"
THRESHOLDS_YAML = EVAL_DIR / "thresholds.yaml"


@dataclass(frozen=True)
class QueryResult:
    query_id: str
    mode: str
    retrieved_files: list[str]
    retrieved_symbols: list[str]
    expected_files: list[str]
    expected_symbols: list[str]


@dataclass(frozen=True)
class EvalReport:
    query_results: list[QueryResult]
    recall_at_5_files: float
    precision_at_3_files: float
    recall_at_5_symbols: float
    mrr_files: float


RetrievalFn = Callable[[str, str, Path], tuple[list[str], list[str]]]
# (query_text, mode, repo_path) -> (retrieved_files_ordered, retrieved_symbols_ordered)


def load_queries() -> list[dict[str, Any]]:
    data = yaml.safe_load(QUERIES_YAML.read_text(encoding="utf-8"))
    queries = data["queries"]
    assert isinstance(queries, list)
    return queries


def load_thresholds() -> dict[str, Any]:
    data = yaml.safe_load(THRESHOLDS_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def run_eval(retrieve: RetrievalFn, *, repo_path: Path = FIXTURE_REPO) -> EvalReport:
    queries = load_queries()
    results: list[QueryResult] = []
    for q in queries:
        retrieved_files, retrieved_symbols = retrieve(q["text"], q["mode"], repo_path)
        expected = q.get("expected", {}) or {}
        results.append(
            QueryResult(
                query_id=q["id"],
                mode=q["mode"],
                retrieved_files=list(retrieved_files),
                retrieved_symbols=list(retrieved_symbols),
                expected_files=list(expected.get("files", []) or []),
                expected_symbols=list(expected.get("symbols", []) or []),
            )
        )

    recall_5_files = _avg(
        recall_at_k(r.retrieved_files, r.expected_files, k=5) for r in results
    )
    precision_3_files = _avg(
        precision_at_k(r.retrieved_files, r.expected_files, k=3) for r in results
    )
    recall_5_symbols = _avg(
        recall_at_k(r.retrieved_symbols, r.expected_symbols, k=5) for r in results
    )
    mrr_f = mean_reciprocal_rank(
        [r.retrieved_files for r in results],
        [r.expected_files for r in results],
    )

    return EvalReport(
        query_results=results,
        recall_at_5_files=recall_5_files,
        precision_at_3_files=precision_3_files,
        recall_at_5_symbols=recall_5_symbols,
        mrr_files=mrr_f,
    )


def _avg(values: "Any") -> float:  # noqa: UP037
    lst = list(values)
    if not lst:
        return 0.0
    return float(sum(lst) / len(lst))


def stub_retrieve(query: str, mode: str, repo_path: Path) -> tuple[list[str], list[str]]:
    """Phase 0 placeholder — returns nothing. Exists so the harness is runnable."""
    return [], []


if __name__ == "__main__":
    report = run_eval(stub_retrieve)
    print(f"recall@5 files   : {report.recall_at_5_files:.3f}")
    print(f"precision@3 files: {report.precision_at_3_files:.3f}")
    print(f"recall@5 symbols : {report.recall_at_5_symbols:.3f}")
    print(f"MRR (files)      : {report.mrr_files:.3f}")
