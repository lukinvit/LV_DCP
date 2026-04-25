"""Typer app — wires subcommands."""

from __future__ import annotations

import sys
from pathlib import Path

import structlog
import typer

# Route structlog output to stderr so `--json` subcommands can keep stdout pure
# (e.g. `ctx scan --json | jq`). Without this, structlog defaults to stdout via
# `PrintLoggerFactory` and timeline / wiki / embedding diagnostics interleave
# with the JSON payload, breaking downstream parsers. Configured at the CLI
# entry point so it applies uniformly to every subcommand without each command
# having to re-route logs itself. MUST run before subcommand modules are
# imported because their lazy-loaded structlog loggers cache the factory at
# `get_logger()` time.
structlog.configure(
    logger_factory=structlog.WriteLoggerFactory(file=sys.stderr),
)

from apps.cli.commands import eval_cmd as eval_module  # noqa: E402
from apps.cli.commands import inspect as inspect_module  # noqa: E402
from apps.cli.commands import (  # noqa: E402
    mcp_cmd,
    memory_cmd,
    obsidian_cmd,
    project_cmd,
    registry_cmd,
    timeline_cmd,
    watch_cmd,
    wiki_cmd,
)
from apps.cli.commands import pack as pack_module  # noqa: E402
from apps.cli.commands import scan as scan_module  # noqa: E402
from apps.cli.commands import setup as setup_module  # noqa: E402
from apps.cli.commands import summarize as summarize_module  # noqa: E402
from apps.cli.commands import ui as ui_module  # noqa: E402

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
    full: bool = typer.Option(
        False,
        "--full",
        help="Force a full re-parse of every file, ignoring content hashes.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the scan result as a JSON object instead of human-readable text. "
            "Schema mirrors `ScanResult` plus `path`, `mode`, and `qdrant_warnings` "
            "(empty list when none). Suppresses all hint text and stderr advisories — "
            "pure data. Composes with --full."
        ),
    ),
) -> None:
    """Scan a project and regenerate .context/*.md artifacts."""
    scan_module.scan(path, full=full, as_json=as_json)


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
app.command()(setup_module.setup)
app.command()(summarize_module.summarize)
app.command()(ui_module.ui)
app.command("eval")(eval_module.eval_cmd)

app.add_typer(mcp_cmd.app, name="mcp")
app.add_typer(watch_cmd.app, name="watch")
app.add_typer(obsidian_cmd.app, name="obsidian")
app.add_typer(wiki_cmd.app, name="wiki")
app.add_typer(memory_cmd.app, name="memory")
app.add_typer(timeline_cmd.app, name="timeline")
app.add_typer(project_cmd.app, name="project")
app.add_typer(registry_cmd.app, name="registry")
