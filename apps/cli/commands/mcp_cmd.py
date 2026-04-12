"""`ctx mcp serve`, `ctx mcp install`, `ctx mcp uninstall` subcommands."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import typer
from libs.core.version import LVDCP_VERSION
from libs.mcp_ops.claude_cli import ClaudeCliError
from libs.mcp_ops.doctor import render_json, render_table, run_doctor
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


_HOOKS_SRC = Path(__file__).resolve().parent.parent / "mcp" / "hooks"
_HOOKS_DST = Path.home() / ".claude" / "hooks"

_HOOK_CONFIGS = {
    "PreToolUse": [
        {
            "matcher": "Grep|Read",
            "hooks": [
                {
                    "type": "command",
                    "command": "bash ~/.claude/hooks/lvdcp-precheck.sh",
                    "timeout": 5,
                    "statusMessage": "Checking LV_DCP index...",
                }
            ],
        }
    ],
    "PostToolUse": [
        {
            "matcher": "Write|Edit",
            "hooks": [
                {
                    "type": "command",
                    "command": "bash ~/.claude/hooks/lvdcp-autoscan.sh",
                    "timeout": 10,
                    "async": True,
                }
            ],
        }
    ],
}


def _install_hooks() -> list[str]:
    """Copy hook scripts and merge hook config into ~/.claude/settings.json."""
    installed: list[str] = []

    # Copy hook scripts
    _HOOKS_DST.mkdir(parents=True, exist_ok=True)
    for src in _HOOKS_SRC.glob("*.sh"):
        dst = _HOOKS_DST / src.name
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        installed.append(str(dst))

    # Merge hook config into settings.json
    settings_path = Path.home() / ".claude" / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))

    hooks = settings.setdefault("hooks", {})
    for event, entries in _HOOK_CONFIGS.items():
        existing = hooks.get(event, [])
        existing_matchers = {e.get("matcher") for e in existing}
        for entry in entries:
            if entry["matcher"] not in existing_matchers:
                existing.append(entry)
        hooks[event] = existing

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")

    return installed


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

    # Install hooks
    hook_files = _install_hooks()
    for hf in hook_files:
        typer.echo(f"hook installed: {hf}")
    typer.echo("hooks: PreToolUse (lvdcp_pack reminder) + PostToolUse (auto-rescan)")

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


@app.command("doctor")
def doctor(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of the human-readable table",
    ),
) -> None:
    """Run diagnostic checks on the lvdcp install state."""
    home = Path.home()
    report = run_doctor(
        config_path=home / ".lvdcp" / "config.yaml",
        claudemd_path=home / ".claude" / "CLAUDE.md",
        settings_legacy_path=home / ".claude" / "settings.json",
        expected_version=LVDCP_VERSION,
    )
    if json_output:
        typer.echo(render_json(report))
    else:
        typer.echo(render_table(report))
    raise typer.Exit(code=report.exit_code)
