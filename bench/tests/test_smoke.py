"""Smoke tests for the standalone devctx_bench package.

These run under the top-level LV_DCP pytest, so we import the package via
its source path. In a real `pip install devctx-bench` environment the
imports would be flat.
"""

from __future__ import annotations

import sys
from pathlib import Path

BENCH_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(BENCH_SRC))


def test_package_has_version() -> None:
    import devctx_bench

    assert devctx_bench.__version__ == "0.1.0"


def test_public_api_is_stable() -> None:
    import devctx_bench

    expected = {
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
    }
    assert expected <= set(devctx_bench.__all__)


def test_metrics_recall_at_k_is_deterministic() -> None:
    from devctx_bench import recall_at_k

    assert recall_at_k(["a", "b", "c"], ["a", "b"], k=2) == 1.0
    assert recall_at_k(["x", "y"], ["a"], k=5) == 0.0
    assert recall_at_k([], [], k=5) == 1.0  # empty ground truth == no miss


def test_stub_retriever_runs_without_error(tmp_path: Path) -> None:
    import yaml

    from devctx_bench import load_queries_file, run_eval
    from devctx_bench.runner import stub_retrieve

    qfile = tmp_path / "q.yaml"
    qfile.write_text(
        yaml.safe_dump(
            {
                "queries": [
                    {"id": "q1", "text": "x", "mode": "navigate", "expected": {"files": ["a.py"]}},
                ]
            }
        )
    )
    queries = load_queries_file(qfile)
    report = run_eval(stub_retrieve, repo_path=tmp_path, navigate_queries=queries)
    assert report.recall_at_5_files == 0.0  # stub returns nothing
    assert report.mrr_files == 0.0


def test_report_rendering_includes_all_metrics() -> None:
    from devctx_bench import generate_per_query_report
    from devctx_bench.runner import EvalReport, QueryResult

    qr = QueryResult(
        query_id="q1",
        mode="navigate",
        retrieved_files=["a.py"],
        retrieved_symbols=[],
        expected_files=["a.py"],
        expected_symbols=[],
    )
    report = EvalReport(
        query_results=[qr],
        recall_at_5_files=1.0,
        precision_at_3_files=1.0,
        recall_at_5_symbols=1.0,
        mrr_files=1.0,
        impact_recall_at_5=0.0,
    )
    md = generate_per_query_report(report)
    assert "recall@5 files:    1.000" in md
    assert "q1" in md
