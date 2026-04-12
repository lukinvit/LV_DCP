"""Tests for the per-query eval report generator."""

from __future__ import annotations

from tests.eval.run_eval import EvalReport, QueryResult, generate_per_query_report


def _make_report() -> EvalReport:
    return EvalReport(
        query_results=[
            QueryResult(
                query_id="q01-user-model",
                mode="navigate",
                retrieved_files=["app/models/user.py", "app/services/auth.py"],
                retrieved_symbols=["app.models.user.User"],
                expected_files=["app/models/user.py"],
                expected_symbols=["app.models.user.User"],
            ),
            QueryResult(
                query_id="q04-refresh-flow",
                mode="navigate",
                retrieved_files=["app/services/auth.py", "app/models/session.py"],
                retrieved_symbols=[],
                expected_files=["app/handlers/auth.py", "app/services/auth.py"],
                expected_symbols=[],
            ),
        ],
        recall_at_5_files=0.750,
        precision_at_3_files=0.500,
        recall_at_5_symbols=1.000,
        mrr_files=0.750,
        impact_recall_at_5=0.000,
    )


def test_report_contains_summary_metrics() -> None:
    md = generate_per_query_report(_make_report())
    assert "recall@5 files" in md
    assert "0.750" in md
    assert "precision@3 files" in md
    assert "impact_recall@5" in md


def test_report_contains_per_query_table() -> None:
    md = generate_per_query_report(_make_report())
    assert "q01-user-model" in md
    assert "q04-refresh-flow" in md
    assert "app/handlers/auth.py" in md  # missed file shown


def test_report_shows_dash_for_no_misses() -> None:
    md = generate_per_query_report(_make_report())
    lines = [line for line in md.splitlines() if "q01-user-model" in line]
    assert len(lines) == 1
    assert "—" in lines[0]  # no missed files


def test_report_is_valid_markdown_table() -> None:
    md = generate_per_query_report(_make_report())
    table_lines = [line for line in md.splitlines() if line.startswith("|")]
    assert len(table_lines) >= 4  # header + separator + 2 data rows
    for line in table_lines:
        assert line.endswith("|")
