"""`ctx mcp serve`, `ctx mcp install`, `ctx mcp uninstall` subcommands."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

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
    settings: dict[str, Any] = {}
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


_RESUME_HOOK_SRC = Path(__file__).resolve().parents[2] / "mcp" / "hooks"

_RESUME_HOOK_CONFIGS = {
    "Stop": [
        {
            "matcher": "lvdcp-resume",
            "hooks": [
                {
                    "type": "command",
                    "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-stop.sh",
                    "timeout": 5,
                }
            ],
        }
    ],
    "PreCompact": [
        {
            "matcher": "lvdcp-resume",
            "hooks": [
                {
                    "type": "command",
                    "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-precompact.sh",
                    "timeout": 5,
                }
            ],
        }
    ],
    "SubagentStop": [
        {
            "matcher": "lvdcp-resume",
            "hooks": [
                {
                    "type": "command",
                    "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-subagent-stop.sh",
                    "timeout": 5,
                }
            ],
        }
    ],
    "SessionStart": [
        {
            "matcher": "lvdcp-resume",
            "hooks": [
                {
                    "type": "command",
                    "command": "$HOME/.claude/hooks/lvdcp/lvdcp-resume-sessionstart.sh",
                    "timeout": 5,
                }
            ],
        }
    ],
}


@dataclass(frozen=True)
class ResumeHooksInstallResult:
    events_added: list[str] = field(default_factory=list)
    files_copied: list[str] = field(default_factory=list)


def _install_resume_hooks(
    *, include_inject: bool, include_schedule: bool
) -> ResumeHooksInstallResult:
    """Copy resume hook scripts and merge their config into ~/.claude/settings.json."""
    resume_hook_dst = Path.home() / ".claude" / "hooks" / "lvdcp"
    resume_hook_dst.mkdir(parents=True, exist_ok=True)
    files_copied: list[str] = []
    for src in _RESUME_HOOK_SRC.glob("lvdcp-resume-*.sh"):
        if not include_inject and src.name.endswith("-sessionstart.sh"):
            continue
        dst = resume_hook_dst / src.name
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        files_copied.append(str(dst))

    settings_path = Path.home() / ".claude" / "settings.json"
    settings: dict[str, Any] = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.setdefault("hooks", {})
    events_added: list[str] = []
    for event, entries in _RESUME_HOOK_CONFIGS.items():
        if not include_inject and event == "SessionStart":
            continue
        existing = hooks.get(event, [])
        existing_matchers = {e.get("matcher") for e in existing}
        for entry in entries:
            if entry["matcher"] not in existing_matchers:
                existing.append(entry)
                events_added.append(event)
        hooks[event] = existing
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")

    if include_schedule:
        from libs.mcp_ops.launchd import bootstrap_breadcrumb_prune  # noqa: PLC0415

        bootstrap_breadcrumb_prune()

    return ResumeHooksInstallResult(
        events_added=events_added,
        files_copied=files_copied,
    )


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
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the install descriptor as a single JSON object: "
            "`{scope, entry_command, entry_args, claudemd_path, "
            "config_path, config_created, version, hooks_installed}`. "
            "Pure data on stdout — suppresses the human "
            "`lvdcp MCP server registered ... / CLAUDE.md managed "
            "section: ... / entry point: ... / hook installed: ...` "
            "chrome. `entry_args` and `hooks_installed` stay JSON arrays "
            "so consumers can introspect individual elements via "
            "`jq -r '.entry_args[0]'` for the interpreter or "
            "`jq -r '.hooks_installed[]'` for each hook script. "
            "`config_created` is the explicit signal that distinguishes "
            "a fresh install from a re-install over an existing config. "
            "Combine with `--dry-run` to emit the planned-config "
            "snippet alone (no `# Copy the following ...` comment "
            "header) so the output parses with `jq` as-is. On "
            "`ClaudeCliError` exit 1 to stderr is preserved with **no** "
            "payload on stdout — same v0.8.42-v0.8.63 error-vs-success "
            "boundary."
        ),
    ),
    hooks: Annotated[
        str | None,
        typer.Option(
            "--hooks",
            help=(
                'Optional hook bundle. Use "resume" to install resume hooks. '
                'Suffixes ":no-inject" / ":no-schedule" disable parts.'
            ),
        ),
    ] = None,
) -> None:
    """Install the lvdcp MCP server via `claude mcp add`.

    With ``--json`` the success-side payload includes the resolved
    `entry_command` (the Python interpreter `claude` will spawn) and
    `entry_args` so an ops script can verify launchd/Claude received
    the expected interpreter — catches the same post-`uv sync`
    interpreter-drift footgun the v0.8.62 install-service descriptor
    addresses for the launchd surface. The `claudemd_path` and
    `config_path` round-trip so a follow-up `ctx mcp uninstall` can
    be scripted from the same payload without re-deriving paths.
    """
    entry_command = sys.executable
    entry_args = ["-m", "apps.mcp.server"]

    if dry_run:
        snippet = build_dry_run_snippet(
            server_name="lvdcp",
            command=entry_command,
            args=entry_args,
            scope=scope,
        )
        if as_json:
            # In JSON mode the snippet is the entire stdout payload. The
            # `# Copy ...` comment is suppressed so `ctx mcp install
            # --json --dry-run | jq .` parses without a stripping step.
            typer.echo(snippet)
            return
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

    # Install hooks (always — same on-disk side effects in both modes)
    hook_files = _install_hooks()

    # Optional resume hook bundle — runs before any early return so both
    # --json and text modes pick it up.
    if hooks:
        parts = hooks.split(":")
        if parts[0] != "resume":
            typer.echo(f"unknown --hooks value: {hooks}", err=True)
            raise typer.Exit(code=2)
        suffixes = set(parts[1:])
        _install_resume_hooks(
            include_inject="no-inject" not in suffixes,
            include_schedule="no-schedule" not in suffixes,
        )

    if as_json:
        payload: dict[str, object] = {
            "scope": result.scope,
            "entry_command": result.entry_command,
            "entry_args": list(result.entry_args),
            "claudemd_path": str(result.claudemd_path),
            "config_path": str(result.config_path),
            "config_created": result.config_created,
            "version": result.version,
            "hooks_installed": list(hook_files),
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(f"lvdcp MCP server registered (scope={result.scope})")
    typer.echo(f"CLAUDE.md managed section: {result.claudemd_path}")
    if result.config_created:
        typer.echo(f"config bootstrapped:       {result.config_path}")
    typer.echo(f"entry point: {result.entry_command} {' '.join(result.entry_args)}")

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
