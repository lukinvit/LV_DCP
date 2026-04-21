"""``ctx eval`` — retrieval eval harness and history (see specs/006, T018).

Three subcommands:

- ``ctx eval run <project> --queries PATH [--output PATH] [--save-to DIR]
  [--baseline aider]`` — run the eval harness and print a Markdown report.
- ``ctx eval compare <a> <b>`` — diff two saved runs.
- ``ctx eval history [--dir DIR] [--limit N]`` — list recent saved runs.
"""

from __future__ import annotations

from pathlib import Path

import typer
from libs.eval.history import (
    compare as compare_reports,
)
from libs.eval.history import (
    latest_runs,
    load_run,
    save_run,
)
from libs.eval.loader import load_optional_queries_file, load_queries_file
from libs.eval.report import generate_comparison_report, generate_per_query_report
from libs.eval.runner import run_eval
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError

DEFAULT_HISTORY_DIR = Path("eval-results")

app = typer.Typer(
    name="eval",
    help="Run the retrieval eval harness and inspect run history.",
    no_args_is_help=True,
)


def _lvdcp_retriever(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    """RetrievalFn backed by the already-indexed ProjectIndex."""
    with ProjectIndex.open(repo) as idx:
        result = idx.retrieve(query, mode=mode, limit=10)
        return list(result.files), list(result.symbols)


@app.command("run")
def run_subcommand(  # noqa: PLR0913
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
    save_to: Path | None = typer.Option(  # noqa: B008
        None,
        "--save-to",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Also persist a JSON snapshot to this directory (for history / compare).",
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

    if save_to is not None:
        snapshot = save_run(primary, save_to)
        typer.echo(f"saved snapshot: {snapshot}")


@app.command("compare")
def compare_subcommand(
    before: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to the baseline snapshot JSON.",
    ),
    after: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to the candidate snapshot JSON.",
    ),
) -> None:
    """Print a metric-level diff between two saved eval runs."""
    a_report = load_run(before)
    b_report = load_run(after)
    diff = compare_reports(
        a_report,
        b_report,
        a_label=before.stem,
        b_label=after.stem,
    )

    lines = [
        f"| metric | {diff.a_label} | {diff.b_label} | delta |",
        "|---|---|---|---|",
    ]
    for d in diff.deltas:
        before_s = "—" if d.before is None else f"{d.before:.3f}"
        after_s = "—" if d.after is None else f"{d.after:.3f}"
        delta_s = (
            "—"
            if d.delta is None
            else ("+" if d.delta >= 0 else "") + f"{d.delta:.3f}"
        )
        lines.append(f"| {d.name} | {before_s} | {after_s} | {delta_s} |")
    typer.echo("\n".join(lines))


@app.command("history")
def history_subcommand(
    directory: Path = typer.Option(  # noqa: B008
        DEFAULT_HISTORY_DIR,
        "--dir",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Directory containing saved eval run snapshots.",
    ),
    limit: int = typer.Option(10, "--limit", min=1, help="Max entries to list."),
) -> None:
    """List the most recent saved eval runs with their headline metrics."""
    runs = latest_runs(directory, limit=limit)
    if not runs:
        typer.echo(f"no eval runs in {directory}")
        return

    lines = [
        "| run | recall@5 | precision@3 | symbols@5 | mrr | impact | ragas cp |",
        "|---|---|---|---|---|---|---|",
    ]
    for path in runs:
        r = load_run(path)
        cp = "—" if r.ragas is None or r.ragas.context_precision is None else f"{r.ragas.context_precision:.3f}"
        lines.append(
            f"| {path.name} | {r.recall_at_5_files:.3f} | "
            f"{r.precision_at_3_files:.3f} | {r.recall_at_5_symbols:.3f} | "
            f"{r.mrr_files:.3f} | {r.impact_recall_at_5:.3f} | {cp} |"
        )
    typer.echo("\n".join(lines))


# Legacy name kept for backwards-compat imports elsewhere (e.g. main.py before
# the refactor referenced ``eval_cmd``). New callers should import ``app``.
eval_cmd = run_subcommand
