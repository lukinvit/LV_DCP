"""`ctx mcp serve`, `ctx mcp install`, `ctx mcp uninstall` subcommands."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from apps.mcp.install import (
    install_claudemd_section,
    install_mcp_settings,
    uninstall_claudemd_section,
    uninstall_mcp_settings,
)
from apps.mcp.server import run_stdio

app = typer.Typer(name="mcp", help="LV_DCP MCP server commands")


def _resolve_claude_paths(scope: str) -> tuple[Path, Path]:
    """Return (claudemd_path, settings_path) for the requested scope."""
    home = Path.home()
    if scope == "user":
        return (home / ".claude" / "CLAUDE.md", home / ".claude" / "settings.json")
    if scope == "project":
        cwd = Path.cwd()
        return (cwd / "CLAUDE.md", cwd / ".claude" / "settings.json")
    if scope == "local":
        cwd = Path.cwd()
        return (cwd / "CLAUDE.md", cwd / ".claude" / "settings.local.json")
    raise typer.BadParameter(f"unknown scope: {scope}")


def _entry_point() -> str:
    """Resolve the MCP server entry point for install.

    Uses the current Python interpreter and runs the server as a module.
    This survives uv venv recreation as long as sys.executable is stable.
    """
    python = sys.executable
    return f"{python} -m apps.mcp.server"


@app.command("serve")
def serve() -> None:
    """Run the MCP server via stdio (called by MCP clients, not humans)."""
    run_stdio()


@app.command("install")
def install(
    scope: str = typer.Option(
        "user",
        "--scope",
        help="Where to install: user (~/.claude), project (./CLAUDE.md), or local (gitignored)",
    ),
) -> None:
    """Install the lvdcp MCP server and inject context-discipline rules into CLAUDE.md."""
    claudemd_path, settings_path = _resolve_claude_paths(scope)
    entry = _entry_point()

    install_mcp_settings(settings_path, entry_point=entry)
    install_claudemd_section(claudemd_path)

    typer.echo(f"MCP server registered at {settings_path}")
    typer.echo(f"CLAUDE.md patched at {claudemd_path}")
    typer.echo(f"  Scope: {scope}")
    typer.echo(f"  Entry point: {entry}")


@app.command("uninstall")
def uninstall(
    scope: str = typer.Option(
        "user",
        "--scope",
        help="Scope to uninstall from (must match install scope)",
    ),
) -> None:
    """Remove the lvdcp MCP server registration and CLAUDE.md managed section."""
    claudemd_path, settings_path = _resolve_claude_paths(scope)

    uninstall_claudemd_section(claudemd_path)
    uninstall_mcp_settings(settings_path)

    typer.echo(f"Removed LV_DCP managed section from {claudemd_path}")
    typer.echo(f"Removed lvdcp entry from {settings_path}")
