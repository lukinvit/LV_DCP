"""`ctx project {check,refresh,wiki,ask}` — thin wrapper over ``libs.copilot``.

Every subcommand is a thin Typer shell around one :mod:`libs.copilot`
function. All business logic — state detection, degraded-mode
classification, orchestration — lives in the library; this file only
decides how to render the resulting DTO (text or JSON).

Spec: ``specs/011-project-copilot-wrapper/spec.md``.
"""

from __future__ import annotations

from pathlib import Path

import typer
from libs.copilot import (
    CopilotAskReport,
    CopilotCheckReport,
    CopilotRefreshReport,
    ask_project,
    check_project,
    refresh_project,
    refresh_wiki,
)

app = typer.Typer(
    name="project",
    help=("High-level project copilot — composes scan/pack/wiki/status into one command surface."),
)


# ---- renderers -------------------------------------------------------------


def _render_check(report: CopilotCheckReport, *, as_json: bool) -> str:
    if as_json:
        return report.model_dump_json(indent=2)
    lines: list[str] = []
    lines.append(f"project: {report.project_name}  ({report.project_root})")
    lines.append(f"  scanned:         {report.scanned}")
    lines.append(f"  stale:           {report.stale}")
    lines.append(f"  last scan:       {report.last_scan_at_iso or '(never)'}")
    lines.append(
        f"  index:           files={report.files} symbols={report.symbols} "
        f"relations={report.relations}"
    )
    lines.append(
        f"  wiki:            present={report.wiki_present} "
        f"dirty_modules={report.wiki_dirty_modules}"
    )
    lines.append(f"  qdrant enabled:  {report.qdrant_enabled}")
    if report.degraded_modes:
        lines.append("  degraded modes:")
        for m in report.degraded_modes:
            lines.append(f"    - {m.value}")
    else:
        lines.append("  degraded modes:  none")
    return "\n".join(lines)


def _render_refresh(report: CopilotRefreshReport, *, as_json: bool) -> str:
    if as_json:
        return report.model_dump_json(indent=2)
    lines: list[str] = []
    lines.append(f"project: {report.project_name}  ({report.project_root})")
    lines.append(f"  scanned:          {report.scanned}")
    lines.append(
        f"  scan:             files={report.scan_files} reparsed={report.scan_reparsed} "
        f"elapsed={report.scan_elapsed_seconds:.2f}s"
    )
    lines.append(
        f"  wiki:             refreshed={report.wiki_refreshed} "
        f"modules_updated={report.wiki_modules_updated}"
    )
    if report.messages:
        lines.append("  messages:")
        for m in report.messages:
            lines.append(f"    - {m}")
    return "\n".join(lines)


def _render_ask(report: CopilotAskReport, *, as_json: bool) -> str:
    if as_json:
        return report.model_dump_json(indent=2)
    lines: list[str] = []
    if report.markdown:
        lines.append(report.markdown.rstrip())
        lines.append("")
    lines.append(f"# coverage: {report.coverage}  trace_id: {report.trace_id or '(none)'}")
    if report.suggestions:
        lines.append("# suggestions:")
        for s in report.suggestions:
            lines.append(f"#   - {s}")
    return "\n".join(lines)


# ---- commands --------------------------------------------------------------


@app.command("check")
def check_cmd(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root directory.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the CopilotCheckReport as indented JSON."
    ),
) -> None:
    """Print a snapshot of scan / wiki / retrieval readiness for a project."""
    report = check_project(path)
    typer.echo(_render_check(report, as_json=as_json))


@app.command("refresh")
def refresh_cmd(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root directory.",
    ),
    full: bool = typer.Option(False, "--full", help="Force a full scan, ignoring content hashes."),
    no_wiki: bool = typer.Option(False, "--no-wiki", help="Skip the wiki update step (scan only)."),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the CopilotRefreshReport as indented JSON."
    ),
) -> None:
    """Scan the project and, by default, refresh the wiki — one command."""
    report = refresh_project(path, full=full, refresh_wiki_after=not no_wiki)
    typer.echo(_render_refresh(report, as_json=as_json))


@app.command("wiki")
def wiki_cmd(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root directory.",
    ),
    do_refresh: bool = typer.Option(
        False, "--refresh", help="Regenerate dirty wiki modules (or all with --all)."
    ),
    all_modules: bool = typer.Option(
        False, "--all", help="With --refresh, regenerate ALL modules, not just dirty ones."
    ),
    as_json: bool = typer.Option(False, "--json", help="JSON output."),
) -> None:
    """Inspect or refresh the wiki for a project."""
    if do_refresh:
        report = refresh_wiki(path, all_modules=all_modules)
        typer.echo(_render_refresh(report, as_json=as_json))
        return
    # Read-only: reuse check_project and render just the wiki portion.
    full_report = check_project(path)
    if as_json:
        typer.echo(full_report.model_dump_json(indent=2))
        return
    typer.echo(f"project: {full_report.project_name}  ({full_report.project_root})")
    typer.echo(f"  wiki present:    {full_report.wiki_present}")
    typer.echo(f"  dirty modules:   {full_report.wiki_dirty_modules}")
    if full_report.wiki_dirty_modules > 0:
        typer.echo("  hint: run `ctx project wiki <path> --refresh`")


@app.command("ask")
def ask_cmd(  # noqa: PLR0913 — each Typer Option is a legit user-facing knob
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Project root directory.",
    ),
    query: str = typer.Argument(..., help="Question in natural language."),
    mode: str = typer.Option(
        "navigate", "--mode", help="navigate | edit — shapes the pack layout."
    ),
    limit: int = typer.Option(10, "--limit", help="Top-N files to retain."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Run `ctx scan` first if the project is not scanned."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the CopilotAskReport as indented JSON."
    ),
) -> None:
    """Answer a project-scoped question and flag any degraded retrieval modes."""
    if mode not in {"navigate", "edit"}:
        typer.echo(f"error: --mode must be 'navigate' or 'edit', got {mode!r}", err=True)
        raise typer.Exit(code=2)
    report = ask_project(
        path,
        query,
        mode=mode,
        limit=limit,
        auto_refresh=refresh,
    )
    typer.echo(_render_ask(report, as_json=as_json))
