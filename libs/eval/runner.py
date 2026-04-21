"""Eval harness runner — project-agnostic, CLI-friendly.

Accepts a ``RetrievalFn`` callable and a pre-parsed list of queries. Does
NO I/O itself — file loading is the caller's responsibility (see
:mod:`libs.eval.loader`). This separation keeps the runner testable
without fixtures and lets it work against the synthetic sample_repo,
against real projects, or against a baseline retriever.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libs.eval.metrics import mean_reciprocal_rank, precision_at_k, recall_at_k


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
    impact_recall_at_5: float


RetrievalFn = Callable[[str, str, Path], tuple[list[str], list[str]]]
# (query_text, mode, repo_path) -> (retrieved_files_ordered, retrieved_symbols_ordered)


def run_eval(
    retrieve: RetrievalFn,
    *,
    repo_path: Path,
    navigate_queries: list[dict[str, Any]],
    impact_queries: list[dict[str, Any]] | None = None,
) -> EvalReport:
    """Run *retrieve* against the given query set and aggregate metrics.

    - *navigate_queries* and *impact_queries* share the same shape (see
      :mod:`libs.eval.loader`). They're kept separate so
      ``impact_recall_at_5`` only aggregates over graph-expansion targets.
    - *repo_path* is passed through to the retriever — callers decide how
      the retriever interprets it (index root, fixture path, etc.).
    """
    impact_queries = impact_queries or []
    all_queries = list(navigate_queries) + list(impact_queries)
    impact_ids = {q["id"] for q in impact_queries}

    results: list[QueryResult] = []
    for q in all_queries:
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

    recall_5_files = _avg(recall_at_k(r.retrieved_files, r.expected_files, k=5) for r in results)
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
    impact_results = [r for r in results if r.query_id in impact_ids]
    impact_recall_5 = _avg(
        recall_at_k(r.retrieved_files, r.expected_files, k=5) for r in impact_results
    )

    return EvalReport(
        query_results=results,
        recall_at_5_files=recall_5_files,
        precision_at_3_files=precision_3_files,
        recall_at_5_symbols=recall_5_symbols,
        mrr_files=mrr_f,
        impact_recall_at_5=impact_recall_5,
    )


def _avg(values: Any) -> float:
    lst = list(values)
    if not lst:
        return 0.0
    return float(sum(lst) / len(lst))


def stub_retrieve(query: str, mode: str, repo_path: Path) -> tuple[list[str], list[str]]:
    """Phase 0 placeholder — returns nothing. Exists so the harness is runnable."""
    del query, mode, repo_path
    return [], []
