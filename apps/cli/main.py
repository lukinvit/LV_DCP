"""Typer app — wires subcommands."""

from __future__ import annotations

from pathlib import Path

import typer

from apps.cli.commands import scan as scan_module

# Create main app
app = typer.Typer(
    help="LV_DCP — Developer Context Platform CLI",
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """LV_DCP CLI."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(typer.echo, "Run with --help for usage")


@app.command()
def scan(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to project root directory",
    ),
) -> None:
    """Scan a project and regenerate .context/*.md artifacts."""
    scan_module.scan(path)
