"""Tests for the per-query eval report generator."""

from __future__ import annotations

from dataclasses import replace

from libs.eval.ragas_adapter import RagasMetrics, RagasPerQuery

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


def _ragas(q1_fc: float, q2_fc: float | None) -> RagasMetrics:
    """Build a RagasMetrics with per-query scores for the two fixture queries."""
    return RagasMetrics(
        context_precision=0.80,
        context_recall=0.70,
        faithfulness=0.90,
        per_query=[
            RagasPerQuery(
                query_id="q01-user-model",
                context_precision=q1_fc,
                context_recall=q1_fc,
                faithfulness=q1_fc,
            ),
            RagasPerQuery(
                query_id="q04-refresh-flow",
                context_precision=q2_fc,
                context_recall=q2_fc,
                faithfulness=q2_fc,
            ),
        ],
        cache_hits=2,
        cache_misses=4,
    )


def test_report_without_ragas_has_no_judge_section() -> None:
    md = generate_per_query_report(_make_report())
    assert "LLM-judge metrics" not in md
    assert "context_precision" not in md


def test_report_with_ragas_adds_judge_section() -> None:
    enriched = replace(_make_report(), ragas=_ragas(0.85, 0.60))
    md = generate_per_query_report(enriched)
    assert "## LLM-judge metrics" in md
    assert "context_precision: 0.800" in md
    assert "context_recall:    0.700" in md
    assert "faithfulness:      0.900" in md
    assert "cache: 2 hits / 4 misses" in md


def test_report_with_ragas_extends_per_query_columns() -> None:
    enriched = replace(_make_report(), ragas=_ragas(0.85, 0.60))
    md = generate_per_query_report(enriched)
    header = next(line for line in md.splitlines() if line.startswith("| id |"))
    for col in ("cp", "cr", "f"):
        assert f"| {col} " in header or header.endswith(f"| {col} |")
    q1_row = next(line for line in md.splitlines() if "q01-user-model" in line)
    assert "0.85" in q1_row
    q2_row = next(line for line in md.splitlines() if "q04-refresh-flow" in line)
    assert "0.60" in q2_row


def test_report_with_ragas_handles_missing_per_query_scores() -> None:
    enriched = replace(_make_report(), ragas=_ragas(0.85, None))
    md = generate_per_query_report(enriched)
    q2_row = next(line for line in md.splitlines() if "q04-refresh-flow" in line)
    # Three judge columns should render em-dashes for the None triple.
    assert q2_row.count("— |") >= 3


def test_report_with_ragas_handles_aggregate_nones() -> None:
    partial = RagasMetrics(
        context_precision=None,
        context_recall=0.5,
        faithfulness=None,
        per_query=[],
        cache_hits=0,
        cache_misses=0,
    )
    enriched = replace(_make_report(), ragas=partial)
    md = generate_per_query_report(enriched)
    assert "context_precision: —" in md
    assert "context_recall:    0.500" in md
    assert "faithfulness:      —" in md
