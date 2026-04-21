"""Reusable retrieval-eval harness.

Ships with LV_DCP as a public API so users can benchmark retrieval quality
on any project they have indexed. The pytest wrappers under ``tests/eval/``
re-export from here — all core logic lives in this package.

Public entry points:

- :func:`libs.eval.runner.run_eval` — run a retriever against a query set
- :func:`libs.eval.loader.load_queries_file` — parse a queries YAML
- :func:`libs.eval.report.generate_per_query_report` — render markdown
- :mod:`libs.eval.metrics` — pure IR metric functions
"""

from libs.eval.metrics import (
    impact_recall_at_k,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)
from libs.eval.runner import EvalReport, QueryResult, RetrievalFn, run_eval

__all__ = [
    "EvalReport",
    "QueryResult",
    "RetrievalFn",
    "impact_recall_at_k",
    "mean_reciprocal_rank",
    "precision_at_k",
    "recall_at_k",
    "run_eval",
]
