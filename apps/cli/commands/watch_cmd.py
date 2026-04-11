"""`ctx watch add/remove/list/start` subcommands."""

from __future__ import annotations

from pathlib import Path

import typer

from apps.agent.config import add_project, list_projects, remove_project
from apps.agent.daemon import DEFAULT_CONFIG_PATH, run_daemon

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
    """Register a project to be watched by the daemon."""
    add_project(DEFAULT_CONFIG_PATH, path)
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
def start(
    foreground: bool = typer.Option(
        True,
        "--foreground/--background",
        help="Run in foreground (for debugging) or fork to background",
    ),
) -> None:
    """Start the daemon main loop."""
    typer.echo("starting lvdcp-agent daemon (Ctrl+C to stop)")
    run_daemon(foreground=foreground)
