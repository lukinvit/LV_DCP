"""devctx-bench — retrieval-only benchmark harness for code-context tools.

Public API::

    from devctx_bench import run_eval, load_queries_file, recall_at_k

    queries = load_queries_file(Path("queries.yaml"))
    report = run_eval(my_retriever, repo_path=Path("./repo"), navigate_queries=queries)
    print(report.recall_at_5_files)

The harness is intentionally retriever-agnostic: you plug in any callable
that takes ``(query, mode, repo_path)`` and returns
``(retrieved_files, retrieved_symbols)``. Ships metric functions
(recall@k, precision@k, MRR) and a markdown report generator.

Sister package `lv-dcp` (https://github.com/lukinvit/LV_DCP) uses this
harness internally to gate retrieval-quality regressions via CI.
"""

from devctx_bench.loader import load_optional_queries_file, load_queries_file
from devctx_bench.metrics import (
    impact_recall_at_k,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)
from devctx_bench.report import generate_comparison_report, generate_per_query_report
from devctx_bench.runner import EvalReport, QueryResult, RetrievalFn, run_eval

__version__ = "0.1.0"
__all__ = [
    "EvalReport",
    "QueryResult",
    "RetrievalFn",
    "generate_comparison_report",
    "generate_per_query_report",
    "impact_recall_at_k",
    "load_optional_queries_file",
    "load_queries_file",
    "mean_reciprocal_rank",
    "precision_at_k",
    "recall_at_k",
    "run_eval",
]
