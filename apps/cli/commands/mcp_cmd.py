"""`ctx mcp serve`, `ctx mcp install`, `ctx mcp uninstall` subcommands."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from libs.core.version import LVDCP_VERSION
from libs.mcp_ops.claude_cli import ClaudeCliError
from libs.mcp_ops.install import build_dry_run_snippet, install_lvdcp
from libs.mcp_ops.uninstall import clean_legacy_settings_json, uninstall_lvdcp

from apps.mcp.server import run_stdio

app = typer.Typer(name="mcp", help="LV_DCP MCP server commands")

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"


def _resolve_claudemd_path(scope: str) -> Path:
    home = Path.home()
    if scope == "user":
        return home / ".claude" / "CLAUDE.md"
    if scope == "project":
        return Path.cwd() / "CLAUDE.md"
    if scope == "local":
        return Path.cwd() / "CLAUDE.md"
    raise typer.BadParameter(f"unknown scope: {scope}")


@app.command("serve")
def serve() -> None:
    """Run the MCP server via stdio (called by MCP clients, not humans)."""
    run_stdio()


@app.command("install")
def install(
    scope: str = typer.Option(
        "user",
        "--scope",
        help="MCP scope: user (global), project (./.mcp.json), or local (gitignored)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print a JSON snippet for manual copy instead of calling claude mcp add",
    ),
) -> None:
    """Install the lvdcp MCP server via `claude mcp add`."""
    entry_command = sys.executable
    entry_args = ["-m", "apps.mcp.server"]

    if dry_run:
        snippet = build_dry_run_snippet(
            server_name="lvdcp",
            command=entry_command,
            args=entry_args,
            scope=scope,
        )
        typer.echo('# Copy the following into ~/.claude.json under "mcpServers":')
        typer.echo(snippet)
        return

    claudemd_path = _resolve_claudemd_path(scope)
    try:
        result = install_lvdcp(
            claudemd_path=claudemd_path,
            config_path=DEFAULT_CONFIG_PATH,
            entry_command=entry_command,
            entry_args=entry_args,
            scope=scope,
            version=LVDCP_VERSION,
        )
    except ClaudeCliError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"lvdcp MCP server registered (scope={result.scope})")
    typer.echo(f"CLAUDE.md managed section: {result.claudemd_path}")
    if result.config_created:
        typer.echo(f"config bootstrapped:       {result.config_path}")
    typer.echo(f"entry point: {result.entry_command} {' '.join(result.entry_args)}")
    typer.echo(
        "note: entry point contains an absolute Python path. If you sync "
        "dotfiles across machines, re-run `ctx mcp install` on each host."
    )


@app.command("uninstall")
def uninstall(
    scope: str = typer.Option(
        "user",
        "--scope",
        help="Scope to uninstall from (must match install scope)",
    ),
    legacy_clean: bool = typer.Option(
        False,
        "--legacy-clean",
        help="Also scrub stray lvdcp entry from ~/.claude/settings.json (old broken install)",
    ),
) -> None:
    """Remove the lvdcp MCP server and CLAUDE.md managed section."""
    claudemd_path = _resolve_claudemd_path(scope)
    uninstall_lvdcp(claudemd_path=claudemd_path, scope=scope)
    typer.echo(f"removed managed section from {claudemd_path}")
    typer.echo(f"removed lvdcp MCP registration (scope={scope})")

    if legacy_clean:
        settings_path = Path.home() / ".claude" / "settings.json"
        result = clean_legacy_settings_json(settings_path)
        if result.removed:
            typer.echo(f"cleaned legacy lvdcp pollution from {settings_path}")
        else:
            typer.echo(f"no legacy pollution found in {settings_path}")
