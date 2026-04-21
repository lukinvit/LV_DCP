"""`ctx eval <project> [--queries ...]` — run retrieval eval on an indexed project.

Exposes the eval harness (previously pytest-only) as a CLI so users can
benchmark retrieval quality on their own repositories with their own
queries. Two modes:

- Default: run LV_DCP retrieval against the queries and print a summary.
- ``--baseline aider``: also run the Aider repo-map baseline and print a
  side-by-side comparison table.
"""

from __future__ import annotations

from pathlib import Path

import typer
from libs.eval.loader import load_optional_queries_file, load_queries_file
from libs.eval.report import generate_comparison_report, generate_per_query_report
from libs.eval.runner import run_eval
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError


def _lvdcp_retriever(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    """RetrievalFn backed by the already-indexed ProjectIndex."""
    with ProjectIndex.open(repo) as idx:
        result = idx.retrieve(query, mode=mode, limit=10)
        return list(result.files), list(result.symbols)


def eval_cmd(
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
        help="Write the markdown report to this file instead of stdout.",
    ),
) -> None:
    """Run the retrieval eval harness against an indexed project."""
    try:
        ProjectIndex.open(project).close()
    except ProjectNotIndexedError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(f"hint: run `ctx scan {project}` first.", err=True)
        raise typer.Exit(code=2) from exc

    navigate = load_queries_file(queries)
    impact = load_optional_queries_file(impact_queries) if impact_queries else []

    primary = run_eval(
        _lvdcp_retriever,
        repo_path=project,
        navigate_queries=navigate,
        impact_queries=impact,
    )

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
