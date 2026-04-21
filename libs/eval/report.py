"""Markdown rendering for eval reports."""

from __future__ import annotations

from datetime import UTC, datetime

from libs.eval.runner import EvalReport


def _fmt_opt(v: float | None) -> str:
    """Render an optional metric: ``'-'`` for missing, 3-decimal float otherwise."""
    return "—" if v is None else f"{v:.3f}"


def generate_per_query_report(report: EvalReport, *, tag: str = "eval") -> str:
    """Render a Markdown per-query eval report.

    When ``report.ragas`` is populated (see :func:`libs.eval.runner.enrich_with_ragas`),
    an additional "LLM-judge metrics" section and per-query judge columns are emitted.
    Otherwise the output matches the IR-only report exactly.
    """
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        f"# Eval Report — {ts} — {tag}",
        "",
        "## Summary",
        f"- recall@5 files:    {report.recall_at_5_files:.3f}",
        f"- precision@3 files: {report.precision_at_3_files:.3f}",
        f"- recall@5 symbols:  {report.recall_at_5_symbols:.3f}",
        f"- MRR files:         {report.mrr_files:.3f}",
        f"- impact_recall@5:   {report.impact_recall_at_5:.3f}",
        "",
    ]

    ragas = report.ragas
    if ragas is not None:
        lines.extend(
            [
                "## LLM-judge metrics",
                f"- context_precision: {_fmt_opt(ragas.context_precision)}",
                f"- context_recall:    {_fmt_opt(ragas.context_recall)}",
                f"- faithfulness:      {_fmt_opt(ragas.faithfulness)}",
                f"- cache: {ragas.cache_hits} hits / {ragas.cache_misses} misses",
                "",
            ]
        )

    lines.extend(["## Per-query breakdown", ""])

    judge_by_id: dict[str, tuple[float | None, float | None, float | None]] = {}
    if ragas is not None:
        judge_by_id = {
            p.query_id: (p.context_precision, p.context_recall, p.faithfulness)
            for p in ragas.per_query
        }

    if judge_by_id:
        lines.append("| id | mode | exp_files | recall@5 | missed | cp | cr | f |")
        lines.append("|---|---|---|---|---|---|---|---|")
    else:
        lines.append("| id | mode | exp_files | recall@5 | missed |")
        lines.append("|---|---|---|---|---|")

    for qr in report.query_results:
        if not qr.expected_files:
            continue
        expected_set = set(qr.expected_files)
        retrieved_set = set(qr.retrieved_files[:5])
        hits = expected_set & retrieved_set
        missed = expected_set - retrieved_set
        recall = len(hits) / len(expected_set) if expected_set else 1.0
        missed_str = ", ".join(sorted(missed)) if missed else "—"
        row = (
            f"| {qr.query_id} | {qr.mode} | {len(expected_set)} | "
            f"{recall:.2f} | {missed_str} |"
        )
        if judge_by_id:
            cp, cr, f = judge_by_id.get(qr.query_id, (None, None, None))
            row += f" {_fmt_opt(cp)} | {_fmt_opt(cr)} | {_fmt_opt(f)} |"
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


def generate_comparison_report(
    primary: EvalReport,
    baseline: EvalReport,
    *,
    primary_label: str = "LV_DCP",
    baseline_label: str = "Baseline",
) -> str:
    """Render a side-by-side comparison of two EvalReports."""
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows = [
        ("recall@5 files", primary.recall_at_5_files, baseline.recall_at_5_files),
        ("precision@3 files", primary.precision_at_3_files, baseline.precision_at_3_files),
        ("recall@5 symbols", primary.recall_at_5_symbols, baseline.recall_at_5_symbols),
        ("MRR files", primary.mrr_files, baseline.mrr_files),
        ("impact_recall@5", primary.impact_recall_at_5, baseline.impact_recall_at_5),
    ]
    lines: list[str] = [
        f"# Eval Comparison — {ts}",
        "",
        f"| Metric | {primary_label} | {baseline_label} | Delta |",
        "|---|---|---|---|",
    ]
    for name, p, b in rows:
        delta = p - b
        sign = "+" if delta >= 0 else ""
        lines.append(f"| {name} | {p:.3f} | {b:.3f} | {sign}{delta:.3f} |")
    lines.append("")
    return "\n".join(lines)
