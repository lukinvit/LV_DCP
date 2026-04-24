"""`ctx watch add/remove/list/start` subcommands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from libs.mcp_ops.launchd import (
    LAUNCH_AGENT_LABEL,
    LaunchctlError,
    bootout_agent,
    bootstrap_agent,
    write_plist,
)

from apps.agent.config import add_project, list_projects, remove_project
from apps.agent.daemon import DEFAULT_CONFIG_PATH, run_daemon

LAUNCH_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
AGENT_LOG_DIR = Path.home() / "Library" / "Logs" / "lvdcp-agent"

app = typer.Typer(name="watch", help="Auto-indexing daemon management")


@app.command("add")
def add(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    """Register a project to be watched by the daemon.

    ``ctx watch add`` is an explicit user intent, so we pass
    ``allow_transient=True`` — the user may legitimately want the daemon to
    follow a ship-ceremony worktree or the ``sample_repo`` fixture. Only
    implicit auto-registration (``ctx scan`` on an unregistered path) filters
    transient roots; explicit invocation wins.
    """
    add_project(DEFAULT_CONFIG_PATH, path, allow_transient=True)
    typer.echo(f"added {path}")


@app.command("remove")
def remove(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        resolve_path=True,
    ),
) -> None:
    """Unregister a project."""
    remove_project(DEFAULT_CONFIG_PATH, path)
    typer.echo(f"removed {path}")


@app.command("list")
def list_cmd() -> None:
    """List registered projects."""
    projects = list_projects(DEFAULT_CONFIG_PATH)
    if not projects:
        typer.echo("no projects registered")
        return
    for p in projects:
        typer.echo(f"  {p.root}")


@app.command("start")
def start() -> None:
    """Start the daemon main loop in the foreground (Ctrl+C to stop).

    For a permanent background service, use `ctx watch install-service`
    to register with launchd.
    """
    typer.echo("starting lvdcp-agent daemon (Ctrl+C to stop)")
    run_daemon()


@app.command("install-service")
def install_service() -> None:
    """Install LV_DCP agent as a launchd LaunchAgent (persistent background service)."""
    plist_path = LAUNCH_AGENT_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
    program_arguments = [sys.executable, "-m", "apps.agent.daemon"]
    write_plist(
        target_path=plist_path,
        program_arguments=program_arguments,
        log_dir=AGENT_LOG_DIR,
    )
    try:
        bootstrap_agent(plist_path=plist_path, uid=os.getuid())
    except LaunchctlError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(
            "note: launchctl bootstrap requires an active GUI session — "
            "run from Terminal.app on the desktop, not from SSH.",
            err=True,
        )
        raise typer.Exit(code=3) from exc
    typer.echo(f"plist written: {plist_path}")
    typer.echo(f"launchctl bootstrap gui/{os.getuid()} succeeded")


@app.command("uninstall-service")
def uninstall_service() -> None:
    """Remove LV_DCP agent launchd LaunchAgent."""
    plist_path = LAUNCH_AGENT_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
    try:
        bootout_agent(uid=os.getuid())
    except LaunchctlError as exc:
        typer.echo(f"note: {exc}", err=True)
    if plist_path.exists():
        plist_path.unlink()
        typer.echo(f"removed plist: {plist_path}")
    else:
        typer.echo(f"no plist at {plist_path}")
