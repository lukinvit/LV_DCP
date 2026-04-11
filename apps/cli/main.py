"""Typer app — wires subcommands."""

from __future__ import annotations

from pathlib import Path

import typer

from apps.cli.commands import inspect as inspect_module
from apps.cli.commands import mcp_cmd, watch_cmd
from apps.cli.commands import pack as pack_module
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


@app.command()
def inspect(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    """Print index stats for a scanned project."""
    inspect_module.inspect(path)


app.command()(pack_module.pack)

app.add_typer(mcp_cmd.app, name="mcp")
app.add_typer(watch_cmd.app, name="watch")
