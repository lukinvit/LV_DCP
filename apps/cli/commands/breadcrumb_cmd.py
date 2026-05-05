"""`ctx breadcrumb` command family."""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
from libs.breadcrumbs.cc_identity import resolve_cc_account_email
from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.prune import prune_older_than
from libs.breadcrumbs.reader import load_recent
from libs.breadcrumbs.store import DEFAULT_STORE_PATH, BreadcrumbStore
from libs.breadcrumbs.writer import write_hook_event

app = typer.Typer(help="Breadcrumb maintenance commands")

_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_UNITS: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(s: str) -> float:
    m = _DURATION_RE.match(s.strip())
    if not m:
        raise typer.BadParameter(f"invalid duration: {s!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]


@app.command("capture")
def capture(
    source: Annotated[str, typer.Option("--source", help="Hook source name")],
    cc_session_id: Annotated[str | None, typer.Option("--cc-session-id")] = None,
    todo_file: Annotated[Path | None, typer.Option("--todo-file")] = None,
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    summary_from_stdin: Annotated[bool, typer.Option("--summary-from-stdin")] = False,
) -> None:
    """Append a hook-sourced breadcrumb. Always exit 0; never blocks CC."""
    try:
        try:
            src = BreadcrumbSource(source)
        except ValueError:
            sys.stderr.write(f"unknown source {source!r}, ignoring\n")
            return
        project_root = os.environ.get("CLAUDE_PROJECT_DIR") or str(Path.cwd())
        todo_snapshot: list[dict[str, object]] | None = None
        if todo_file is not None and todo_file.exists():
            try:
                todo_snapshot = json.loads(todo_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                todo_snapshot = None
        if summary_from_stdin and not summary:
            summary = sys.stdin.read()
        store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
        store.migrate()
        try:
            write_hook_event(
                store=store,
                source=src,
                project_root=project_root,
                os_user=getpass.getuser(),
                cc_session_id=cc_session_id or os.environ.get("CLAUDE_SESSION_ID"),
                cc_account_email=resolve_cc_account_email(),
                todo_snapshot=todo_snapshot,
                turn_summary=summary,
            )
        finally:
            store.close()
    except Exception as exc:
        sys.stderr.write(f"breadcrumb capture failed (suppressed): {exc}\n")


@app.command("list")
def list_(
    path: Annotated[Path | None, typer.Option("--path")] = None,
    since: Annotated[str, typer.Option("--since", help="e.g. 12h, 7d, 30m")] = "12h",
    limit: Annotated[int, typer.Option("--limit")] = 50,
    include_other_users: Annotated[bool, typer.Option("--include-other-users")] = False,
) -> None:
    """List recent breadcrumbs for the current project."""
    project_root = str((path or Path.cwd()).resolve())
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
    store.migrate()
    try:
        rows = load_recent(
            store=store,
            project_root=project_root,
            os_user=getpass.getuser(),
            since_ts=time.time() - _parse_duration(since),
            limit=limit,
            cc_account_email=None if include_other_users else resolve_cc_account_email(),
        )
        for r in rows:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp))
            typer.echo(f"{ts}  {r.source:18s}  {r.mode or '-':9s}  {r.query or ''}")
    finally:
        store.close()


@app.command("prune")
def prune(
    older_than: Annotated[str, typer.Option("--older-than")] = "14d",
    project: Annotated[Path | None, typer.Option("--project")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Delete breadcrumbs older than a given age."""
    cutoff = time.time() - _parse_duration(older_than)
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
    store.migrate()
    try:
        if dry_run:
            conn = store.connect()
            sql = "SELECT COUNT(*) FROM breadcrumbs WHERE timestamp < ?"
            params: tuple[float] | tuple[float, str] = (cutoff,)
            if project is not None:
                sql += " AND project_root = ?"
                params = (cutoff, str(project.resolve()))
            (cnt,) = conn.execute(sql, params).fetchone()
            typer.echo(f"would prune {cnt} rows")
            return
        deleted = prune_older_than(store=store, cutoff_ts=cutoff)
        typer.echo(f"pruned {deleted} rows")
    finally:
        store.close()


@app.command("purge")
def purge(project: Annotated[Path, typer.Option("--project")]) -> None:
    """Purge all breadcrumbs for a specific project."""
    store = BreadcrumbStore(db_path=DEFAULT_STORE_PATH)
    store.migrate()
    try:
        conn = store.connect()
        cur = conn.execute(
            "DELETE FROM breadcrumbs WHERE project_root = ?",
            (str(project.resolve()),),
        )
        conn.commit()
        typer.echo(f"purged {cur.rowcount or 0} rows")
    finally:
        store.close()


@app.command("privacy")
def privacy(
    project: Annotated[Path, typer.Option("--project")],
    mode: Annotated[str, typer.Option("--mode")],
) -> None:
    """Set privacy mode for a project's breadcrumbs."""
    if mode == "full_sync":
        typer.echo("error: full_sync is reserved for Phase 8+; use local_only", err=True)
        raise typer.Exit(code=2)
    if mode != "local_only":
        typer.echo(f"error: unknown mode {mode!r}", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"privacy mode for {project} set to {mode}")
