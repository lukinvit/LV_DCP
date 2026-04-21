"""Markdown rendering for eval reports."""

from __future__ import annotations

from datetime import UTC, datetime

from devctx_bench.runner import EvalReport


def generate_per_query_report(report: EvalReport, *, tag: str = "eval") -> str:
    """Render a Markdown per-query eval report."""
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
        "## Per-query breakdown",
        "",
        "| id | mode | exp_files | recall@5 | missed |",
        "|---|---|---|---|---|",
    ]
    for qr in report.query_results:
        if not qr.expected_files:
            continue
        expected_set = set(qr.expected_files)
        retrieved_set = set(qr.retrieved_files[:5])
        hits = expected_set & retrieved_set
        missed = expected_set - retrieved_set
        recall = len(hits) / len(expected_set) if expected_set else 1.0
        missed_str = ", ".join(sorted(missed)) if missed else "—"
        lines.append(
            f"| {qr.query_id} | {qr.mode} | {len(expected_set)} | {recall:.2f} | {missed_str} |"
        )
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
