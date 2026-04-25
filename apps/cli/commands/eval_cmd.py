"""`ctx eval <project> [--queries ...]` — run retrieval eval on an indexed project.

Exposes the eval harness (previously pytest-only) as a CLI so users can
benchmark retrieval quality on their own repositories with their own
queries. Two modes:

- Default: run LV_DCP retrieval against the queries and print a summary.
- ``--baseline aider``: also run the Aider repo-map baseline and print a
  side-by-side comparison table.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer
from libs.eval.loader import load_optional_queries_file, load_queries_file
from libs.eval.report import generate_comparison_report, generate_per_query_report
from libs.eval.runner import EvalReport, run_eval
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError


def _lvdcp_retriever(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    """RetrievalFn backed by the already-indexed ProjectIndex."""
    with ProjectIndex.open(repo) as idx:
        result = idx.retrieve(query, mode=mode, limit=10)
        return list(result.files), list(result.symbols)


def _eval_report_to_json(
    report: EvalReport,
    *,
    project: Path,
    queries_path: Path,
    impact_queries_path: Path | None,
) -> dict[str, object]:
    """Mirror the ``EvalReport`` dataclass schema 1:1 plus the invocation
    parameters that round-trip what this run actually evaluated.

    Schema:
      - ``project``: absolute path of the project root that was evaluated
      - ``queries_path``: absolute path of the navigate queries YAML file
        (round-tripped so a script can confirm the run actually used the
        file it intended, catching ``--queries`` typos without echoing
        back arbitrary input flags)
      - ``impact_queries_path``: absolute path of the impact queries
        YAML file, or ``null`` when ``--impact-queries`` was not passed
        (distinguishes "no impact queries supplied" from "impact queries
        supplied but yielded zero results" — both would collapse to
        ``impact_recall_at_5=0.0`` without this field)
      - ``summary``: aggregate metrics — ``recall_at_5_files``,
        ``precision_at_3_files``, ``recall_at_5_symbols``, ``mrr_files``,
        ``impact_recall_at_5`` — pass-through of the ``EvalReport``
        scalar fields, useful for "did this branch regress retrieval
        quality below threshold" CI gates via
        ``jq -e '.summary.recall_at_5_files >= 0.7'``.
      - ``query_results``: array of per-query rows, one entry per query
        in the input YAMLs (navigate first, then impact). Each row is a
        1:1 mirror of the ``QueryResult`` dataclass: ``query_id``,
        ``mode``, ``retrieved_files``, ``retrieved_symbols``,
        ``expected_files``, ``expected_symbols``. Lets dashboards do
        per-query trend analysis (which queries regressed?) and
        retrieval-pipeline debugging (which queries surfaced the wrong
        files?) without re-parsing the markdown table.

    ``query_results`` order matches the input query file order — same
    semantic as the markdown report, lets consumers correlate per-query
    rows across runs by index without re-keying on ``query_id``.
    """
    return {
        "project": str(project),
        "queries_path": str(queries_path),
        "impact_queries_path": str(impact_queries_path) if impact_queries_path else None,
        "summary": {
            "recall_at_5_files": report.recall_at_5_files,
            "precision_at_3_files": report.precision_at_3_files,
            "recall_at_5_symbols": report.recall_at_5_symbols,
            "mrr_files": report.mrr_files,
            "impact_recall_at_5": report.impact_recall_at_5,
        },
        "query_results": [asdict(qr) for qr in report.query_results],
    }


def eval_cmd(  # noqa: PLR0913 — each Typer Option is a legit user-facing knob
    project: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root (must be indexed — run `ctx scan` first).",
    ),
    queries: Path = typer.Option(  # noqa: B008
        ...,
        "--queries",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to a navigate queries YAML file.",
    ),
    impact_queries: Path | None = typer.Option(  # noqa: B008
        None,
        "--impact-queries",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Optional path to an impact queries YAML file.",
    ),
    baseline: str | None = typer.Option(
        None,
        "--baseline",
        help="Optional baseline retriever to compare against. Only 'aider' is supported.",
    ),
    output: Path | None = typer.Option(  # noqa: B008
        None,
        "--output",
        "-o",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help=(
            "Write the report to this file instead of stdout. With --json the file "
            "receives the JSON payload; without --json the file receives the "
            "human-readable markdown report."
        ),
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a single JSON object mirroring the EvalReport dataclass: "
            "{project, queries_path, impact_queries_path, summary (aggregate "
            "metrics), query_results (per-query rows)} instead of the human-"
            "readable markdown report. Suppresses all hint text — pure data on "
            "stdout. Not yet supported with --baseline (the comparison-report "
            "JSON shape deserves its own ship)."
        ),
    ),
) -> None:
    """Run the retrieval eval harness against an indexed project."""
    try:
        ProjectIndex.open(project).close()
    except ProjectNotIndexedError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(f"hint: run `ctx scan {project}` first.", err=True)
        raise typer.Exit(code=2) from exc

    if as_json and baseline is not None:
        # Comparison reports have a different shape (two EvalReports + diff
        # metrics) that deserves its own ship analysis. Reject the combo
        # cleanly rather than emit a half-defined payload.
        typer.echo(
            "error: --json is not yet supported with --baseline. "
            "Run without --baseline to get the structured payload, or omit --json "
            "for the markdown comparison report.",
            err=True,
        )
        raise typer.Exit(code=2)

    navigate = load_queries_file(queries)
    impact = load_optional_queries_file(impact_queries) if impact_queries else []

    primary = run_eval(
        _lvdcp_retriever,
        repo_path=project,
        navigate_queries=navigate,
        impact_queries=impact,
    )

    if as_json:
        # JSON path: only reachable when baseline is None (gated above).
        payload = _eval_report_to_json(
            primary,
            project=project,
            queries_path=queries,
            impact_queries_path=impact_queries,
        )
        rendered = json.dumps(payload, indent=2)
        if output is not None:
            output.write_text(rendered, encoding="utf-8")
            typer.echo(f"wrote: {output}", err=True)
        else:
            typer.echo(rendered)
        return

    if baseline is None:
        report = generate_per_query_report(primary, tag=f"lvdcp @ {project.name}")
    elif baseline == "aider":
        try:
            # Importing from tests/ because the baseline is a benchmarking
            # artifact, not a shipped retriever. When the package is installed
            # without tests/ on PYTHONPATH, this branch is unavailable and the
            # command must be told so explicitly.
            from tests.eval.baselines.aider_repomap import (  # noqa: PLC0415
                aider_baseline_retrieve,
            )
        except ImportError as exc:
            typer.echo(
                "error: Aider baseline is only available when running from a "
                "source checkout of LV_DCP (needs tests/eval/baselines/).",
                err=True,
            )
            raise typer.Exit(code=3) from exc
        baseline_report = run_eval(
            aider_baseline_retrieve,
            repo_path=project,
            navigate_queries=navigate,
            impact_queries=impact,
        )
        report = generate_comparison_report(
            primary,
            baseline_report,
            primary_label="LV_DCP",
            baseline_label="Aider baseline",
        )
    else:
        typer.echo(f"error: unknown baseline {baseline!r} (supported: aider)", err=True)
        raise typer.Exit(code=2)

    if output is not None:
        output.write_text(report, encoding="utf-8")
        typer.echo(f"wrote: {output}")
    else:
        typer.echo(report)
