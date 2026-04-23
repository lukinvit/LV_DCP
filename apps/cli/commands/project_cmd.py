"""`ctx project {check,refresh,wiki,ask}` — thin wrapper over ``libs.copilot``.

Every subcommand is a thin Typer shell around one :mod:`libs.copilot`
function. All business logic — state detection, degraded-mode
classification, orchestration — lives in the library; this file only
decides how to render the resulting DTO (text or JSON).

Spec: ``specs/011-project-copilot-wrapper/spec.md``.
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from libs.copilot import (
    CopilotAskReport,
    CopilotCheckReport,
    CopilotRefreshReport,
    ask_project,
    cancel_background_refresh,
    check_project,
    refresh_project,
    refresh_wiki,
    watch_check_project,
)

app = typer.Typer(
    name="project",
    help=("High-level project copilot — composes scan/pack/wiki/status into one command surface."),
)


# ---- renderers -------------------------------------------------------------


_SIGTERM_EXIT_CODE = 143


def _format_age(seconds: float) -> str:
    """Human-friendly "N ago" for small durations.

    Chosen to match the compact single-line render; we never show sub-
    second precision here because filesystem mtimes on macOS are second-
    granular anyway.
    """
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


def _format_elapsed(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def _render_last_refresh(report: CopilotCheckReport, *, now: float | None = None) -> str | None:
    """Human-friendly "last refresh" summary, or ``None`` if never run.

    Format:
      ok 12 modules 47s, 3 min ago
      FAILED exit=1 after 8 modules 12s, 3 min ago — see .refresh.log
      cancelled after 3 modules 5s, 3 min ago
    """
    if report.wiki_last_refresh_completed_at is None:
        return None
    exit_code = report.wiki_last_refresh_exit_code or 0
    modules = report.wiki_last_refresh_modules_updated or 0
    elapsed = _format_elapsed(report.wiki_last_refresh_elapsed_seconds or 0.0)
    age = _format_age(
        (now if now is not None else time.time()) - report.wiki_last_refresh_completed_at
    )
    if exit_code == 0:
        return f"ok {modules} modules {elapsed}, {age}"
    if exit_code == _SIGTERM_EXIT_CODE:
        return f"cancelled after {modules} modules {elapsed}, {age}"
    return f"FAILED exit={exit_code} after {modules} modules {elapsed}, {age} — see .refresh.log"


def _render_bg_refresh(report: CopilotCheckReport) -> str:
    """Compact one-line summary of in-flight background wiki refresh.

    Examples:
      ``false``                                            — no refresh running, no record
      ``false (last: ok 12 modules 47s, 3 min ago)``       — previous run succeeded
      ``false (last: FAILED exit=1 …)``                    — previous run crashed
      ``true (starting, pid=1234)``                        — spawned, lock seen
      ``true (generating 3/12 "foo/bar", pid=1234)``       — mid-run
    """
    if not report.wiki_refresh_in_progress:
        last = _render_last_refresh(report)
        return "false" if last is None else f"false (last: {last})"
    parts: list[str] = [report.wiki_refresh_phase or "running"]
    if report.wiki_refresh_modules_total is not None:
        parts.append(f"{report.wiki_refresh_modules_done}/{report.wiki_refresh_modules_total}")
    if report.wiki_refresh_current_module:
        parts.append(f'"{report.wiki_refresh_current_module}"')
    if report.wiki_refresh_pid is not None:
        parts.append(f"pid={report.wiki_refresh_pid}")
    return f"true ({' '.join(parts)})"


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
    bg_label = _render_bg_refresh(report)
    lines.append(
        f"  wiki:            present={report.wiki_present} "
        f"dirty_modules={report.wiki_dirty_modules} "
        f"bg_refresh={bg_label}"
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
        f"bg_started={report.wiki_refresh_background_started} "
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
    watch: bool = typer.Option(
        False,
        "--watch",
        help=(
            "Re-print the snapshot every --interval seconds until any in-flight "
            "background wiki refresh finishes (or --max-duration elapses). "
            "No-op if no refresh is running at start."
        ),
    ),
    interval: float = typer.Option(
        2.0, "--interval", help="Seconds between snapshots in --watch mode."
    ),
    max_duration: float = typer.Option(
        15 * 60,
        "--max-duration",
        help="Safety cap on --watch wall-clock time (seconds). Default 15 min.",
    ),
) -> None:
    """Print a snapshot of scan / wiki / retrieval readiness for a project.

    With ``--watch``, re-print until the background wiki refresh settles.
    Snapshots are separated by a blank line so both the raw text mode and
    the ``--json`` mode remain grep-friendly.
    """
    if not watch:
        report = check_project(path)
        typer.echo(_render_check(report, as_json=as_json))
        return
    first = True
    for report in watch_check_project(
        path, interval_seconds=interval, max_duration_seconds=max_duration
    ):
        if not first:
            typer.echo("")  # blank-line separator between consecutive snapshots
        typer.echo(_render_check(report, as_json=as_json))
        first = False


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
    wiki_background: bool = typer.Option(
        False,
        "--wiki-background",
        help=(
            "Run the wiki refresh as a detached subprocess. The command returns as soon "
            "as the scan finishes; progress is visible in "
            "`.context/wiki/.refresh.log` and via `ctx project check`."
        ),
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit the CopilotRefreshReport as indented JSON."
    ),
) -> None:
    """Scan the project and, by default, refresh the wiki — one command."""
    report = refresh_project(
        path,
        full=full,
        refresh_wiki_after=not no_wiki,
        wiki_background=wiki_background,
    )
    typer.echo(_render_refresh(report, as_json=as_json))


@app.command("wiki")
def wiki_cmd(  # noqa: PLR0913 — each Typer Option is a legit user-facing knob
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
    background: bool = typer.Option(
        False,
        "--background",
        help=(
            "With --refresh, spawn a detached subprocess and return immediately. "
            "Progress is logged to `.context/wiki/.refresh.log`."
        ),
    ),
    stop: bool = typer.Option(
        False,
        "--stop",
        help=(
            "Cancel an in-flight background refresh (sends SIGTERM). "
            "No-op if no refresh is running."
        ),
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "JSON output. Shape: CopilotRefreshReport with --refresh, "
            "CopilotCheckReport in read-only or --stop mode."
        ),
    ),
) -> None:
    """Inspect or refresh the wiki for a project.

    The ``--json`` shape depends on the mode:

    * ``--refresh`` → :class:`libs.copilot.CopilotRefreshReport`
    * read-only (default) and ``--stop`` → :class:`libs.copilot.CopilotCheckReport`

    Scripts that need a single stable shape should call
    ``ctx project check --json`` instead.
    """
    if stop:
        status = cancel_background_refresh(path)
        full_report = check_project(path)
        if as_json:
            typer.echo(full_report.model_dump_json(indent=2))
            return
        if status.pid is not None and not status.stale:
            typer.echo(f"bg refresh: SIGTERM sent to pid={status.pid}")
        elif status.stale:
            typer.echo("bg refresh: stale lock cleared (no live process)")
        else:
            typer.echo("bg refresh: none running")
        return
    if do_refresh:
        report = refresh_wiki(path, all_modules=all_modules, background=background)
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
    typer.echo(f"  bg refresh:      {_render_bg_refresh(full_report)}")
    if full_report.wiki_refresh_in_progress:
        typer.echo(
            "  hint: tail `.context/wiki/.refresh.log`, or stop with `ctx project wiki <path> --stop`"
        )
    elif full_report.wiki_dirty_modules > 0:
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
