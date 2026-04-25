"""`ctx timeline {enable,disable,status,reconcile,prune,backfill}` — operator CLI.

Thin Typer layer on top of :mod:`libs.symbol_timeline`. Stays pure: every
side effect goes through a library function so the commands are trivially
unit-testable with ``typer.testing.CliRunner``.

Spec: specs/010-feature-timeline-index/tasks.md §T034.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from libs.symbol_timeline.reconcile import ReconcileReport, prune_events, reconcile
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    get_scan_state,
    resolve_default_store_path,
)

app = typer.Typer(help="Manage the symbol timeline index for a project.")


# ---- helpers ----------------------------------------------------------------


def _resolve_project(project: Path | None) -> Path:
    return (project or Path.cwd()).resolve()


def _open_store(store_path: Path | None) -> SymbolTimelineStore:
    path = store_path if store_path is not None else resolve_default_store_path()
    store = SymbolTimelineStore(path)
    store.migrate()
    return store


def _flag_file(project_root: Path) -> Path:
    """Return the on/off flag file path for the project.

    ``.context/timeline.enabled`` is a zero-byte marker the agent can check
    before wiring the SqliteTimelineSink into the scanner. When the file is
    absent the default is ``enabled`` (matches ``TimelineConfig.enabled``).
    When the file exists with content ``off`` the agent skips registration.
    """
    return project_root / ".context" / "timeline.enabled"


def _read_flag(project_root: Path) -> bool:
    f = _flag_file(project_root)
    if not f.exists():
        return True
    return f.read_text().strip().lower() != "off"


def _write_flag(project_root: Path, *, enabled: bool) -> None:
    f = _flag_file(project_root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("on\n" if enabled else "off\n")


def _event_counts(store: SymbolTimelineStore, *, project_root: str) -> dict[str, int]:
    rows = (
        store._connect()
        .execute(
            "SELECT event_type, COUNT(*) FROM symbol_timeline_events "
            "WHERE project_root = ? GROUP BY event_type",
            (project_root,),
        )
        .fetchall()
    )
    return {r[0]: r[1] for r in rows}


def _reconcile_report_to_json(report: ReconcileReport) -> dict[str, object]:
    """Build the JSON payload for `ctx timeline reconcile --json`.

    Schema is a 1:1 mirror of the `ReconcileReport` dataclass — adding a
    field there is the single point that surfaces it in both text and JSON
    paths. `orphaned_by_event_type` is alphabetically sorted (dict
    insertion order = deterministic key ordering) so consumers can
    `jq -r '.orphaned_by_event_type | keys[]'` without an explicit sort.
    """
    return {
        "project_root": report.project_root,
        "git_available": report.git_available,
        "reachable_commit_count": report.reachable_commit_count,
        "orphaned_newly_flagged": report.orphaned_newly_flagged,
        "orphaned_by_event_type": dict(sorted(report.orphaned_by_event_type.items())),
    }


def _orphaned_count(store: SymbolTimelineStore, *, project_root: str) -> int:
    row = (
        store._connect()
        .execute(
            "SELECT COUNT(*) FROM symbol_timeline_events WHERE project_root = ? AND orphaned = 1",
            (project_root,),
        )
        .fetchone()
    )
    return int(row[0]) if row else 0


# ---- commands ---------------------------------------------------------------


@app.command("enable")
def enable_cmd(
    project: Path | None = typer.Option(  # noqa: B008
        None, "--project", "-p", help="Project root (defaults to cwd)."
    ),
) -> None:
    """Enable timeline capture for the project."""
    root = _resolve_project(project)
    _write_flag(root, enabled=True)
    typer.echo(f"timeline: enabled for {root}")


@app.command("disable")
def disable_cmd(
    project: Path | None = typer.Option(  # noqa: B008
        None, "--project", "-p", help="Project root (defaults to cwd)."
    ),
) -> None:
    """Disable timeline capture for the project (scanner runs without sink)."""
    root = _resolve_project(project)
    _write_flag(root, enabled=False)
    typer.echo(f"timeline: disabled for {root}")


@app.command("status")
def status_cmd(
    project: Path | None = typer.Option(  # noqa: B008
        None, "--project", "-p", help="Project root (defaults to cwd)."
    ),
    store_path: Path | None = typer.Option(  # noqa: B008
        None, "--store", help="Timeline DB path (defaults to env or platform dir)."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of text."
    ),
) -> None:
    """Show event count, orphaned count, last scan sha, and DB size."""
    root = _resolve_project(project)
    project_root = str(root)
    store = _open_store(store_path)
    try:
        counts = _event_counts(store, project_root=project_root)
        orphaned = _orphaned_count(store, project_root=project_root)
        state = get_scan_state(store, project_root=project_root)
        db_size = store.db_path.stat().st_size if store.db_path.exists() else 0
        enabled = _read_flag(root)
    finally:
        store.close()

    payload = {
        "project_root": project_root,
        "enabled": enabled,
        "db_path": str(store.db_path),
        "db_size_bytes": db_size,
        "event_counts": counts,
        "total_events": sum(counts.values()),
        "orphaned_events": orphaned,
        "last_scan_commit_sha": state.last_scan_commit_sha if state else None,
        "last_scan_ts": state.last_scan_ts if state else None,
    }

    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    typer.echo(f"timeline status for {project_root}")
    typer.echo(f"  enabled:          {enabled}")
    typer.echo(f"  db path:          {store.db_path}")
    typer.echo(f"  db size:          {db_size} B")
    typer.echo(f"  total events:     {sum(counts.values())}")
    for etype in ("added", "modified", "removed", "renamed", "moved"):
        if etype in counts:
            typer.echo(f"    {etype:9}       {counts[etype]}")
    typer.echo(f"  orphaned events:  {orphaned}")
    if state is not None:
        typer.echo(f"  last scan sha:    {state.last_scan_commit_sha}")
        typer.echo(f"  last scan ts:     {state.last_scan_ts}")
    else:
        typer.echo("  last scan sha:    (never scanned)")


@app.command("reconcile")
def reconcile_cmd(
    project: Path | None = typer.Option(  # noqa: B008
        None, "--project", "-p", help="Project root (defaults to cwd)."
    ),
    store_path: Path | None = typer.Option(  # noqa: B008
        None, "--store", help="Timeline DB path."
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the `ReconcileReport` as a JSON object instead of the "
            "human-readable summary. Schema mirrors the dataclass: "
            "`{project_root, git_available, reachable_commit_count, "
            "orphaned_newly_flagged, orphaned_by_event_type}`. The "
            "`git unavailable` failure mode still surfaces on stderr "
            "with exit 1 — JSON output is reserved for the success path "
            "(stdout stays empty on failure, scripts gate on `set -e`). "
            "Composes with --project and --store."
        ),
    ),
) -> None:
    """Mark events whose commit_sha is no longer in the repo as orphaned."""
    root = _resolve_project(project)
    project_root = str(root)
    store = _open_store(store_path)
    try:
        report = reconcile(store, project_root=project_root, git_root=root)
    finally:
        store.close()

    if not report.git_available:
        # Discipline shared with v0.8.42 / v0.8.43 / v0.8.44: --json never
        # swallows the error into a `{"error": "..."}` stdout payload.
        # Splitting that contract — sometimes JSON, sometimes prose, both
        # on stdout — would force every consumer to parse-then-check-keys
        # instead of just relying on `set -e` + `gh-style` exit codes.
        typer.echo("reconcile: git unavailable — no events flagged", err=True)
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps(_reconcile_report_to_json(report), indent=2))
        return

    typer.echo(f"reconcile: {report.orphaned_newly_flagged} newly flagged orphaned")
    typer.echo(f"  reachable commits: {report.reachable_commit_count}")
    for etype, n in sorted(report.orphaned_by_event_type.items()):
        typer.echo(f"  orphaned {etype:9}: {n}")


@app.command("prune")
def prune_cmd(
    older_than_days: int = typer.Option(
        90,
        "--older-than",
        help="Delete events older than this many days (orphaned only by default).",
    ),
    include_live: bool = typer.Option(
        False,
        "--include-live",
        help="Also delete non-orphaned (live) events — use with care.",
    ),
    project: Path | None = typer.Option(  # noqa: B008
        None, "--project", "-p", help="Project root (defaults to cwd)."
    ),
    store_path: Path | None = typer.Option(  # noqa: B008
        None, "--store", help="Timeline DB path."
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the prune result as a single JSON object instead of the "
            "human-readable summary. Schema: `{project_root, store_path, "
            "older_than_days, include_live, deleted}` — round-trips the "
            "invocation parameters so a script can confirm the run actually "
            "targeted the project / store / cutoff it intended (same "
            "v0.8.48/v0.8.50/v0.8.52-v0.8.54 precedent), and surfaces the "
            "raw deleted count for `jq -e '.deleted > 0'` CI gating. The "
            "non-positive `--older-than` failure mode still surfaces on "
            "stderr with exit 2 — JSON output is reserved for the success "
            "path (stdout stays empty on validation failure, scripts gate "
            "on `set -e`). Same scriptability discipline as v0.8.38 "
            "registry prune --json."
        ),
    ),
) -> None:
    """Permanently delete old events. Defaults to orphaned-only — safer."""
    if older_than_days <= 0:
        typer.echo("prune: --older-than must be positive", err=True)
        raise typer.Exit(code=2)
    root = _resolve_project(project)
    project_root = str(root)
    cutoff = time.time() - older_than_days * 86400
    store = _open_store(store_path)
    try:
        deleted = prune_events(
            store,
            project_root=project_root,
            older_than_ts=cutoff,
            only_orphaned=not include_live,
        )
        # Capture the resolved store path *before* close — `store.db_path`
        # remains valid after close (it's just a Path attribute), but reading
        # it inside the try block keeps the read inside the with-resource
        # discipline so a future refactor that invalidates the attribute on
        # close doesn't silently break the JSON shape.
        resolved_store_path = str(store.db_path)
    finally:
        store.close()

    if as_json:
        # Pure data — no headers, no "deleted N events" prose. Same shape
        # discipline as v0.8.38 registry prune --json: 1:1 mirror of "what
        # the command actually did during this run", with invocation
        # parameters round-tripped so the consumer can verify the call
        # without re-deriving from argv.
        typer.echo(
            json.dumps(
                {
                    "project_root": project_root,
                    "store_path": resolved_store_path,
                    "older_than_days": older_than_days,
                    "include_live": include_live,
                    "deleted": deleted,
                },
                indent=2,
            )
        )
        return

    scope = "orphaned + live" if include_live else "orphaned only"
    typer.echo(f"prune: deleted {deleted} events ({scope}, older than {older_than_days}d)")


@app.command("backfill")
def backfill_cmd(
    project: Path | None = typer.Option(  # noqa: B008
        None, "--project", "-p", help="Project root (defaults to cwd)."
    ),
) -> None:
    """Placeholder — run a full `ctx scan` manually to seed the timeline.

    A real backfill path that walks ``git log`` and replays each commit
    through the scanner is an explicit non-goal of Phase 7 — it belongs in
    the post-MVP backlog (see tasks.md §Out of Phase 2 MVP). For now,
    running ``ctx scan <project>`` on the current HEAD is the authoritative
    seed; this command just prints the right command to run.
    """
    root = _resolve_project(project)
    typer.echo(
        "backfill: out of scope for Phase 7. "
        f"Run `ctx scan {root}` to seed the timeline from the current HEAD."
    )
