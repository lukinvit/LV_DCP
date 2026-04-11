"""High-level `ctx mcp install` implementation.

Delegates MCP server registration to `claude mcp add`. Bootstraps
~/.lvdcp/config.yaml if missing. Writes a versioned managed section into
~/.claude/CLAUDE.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from libs.mcp_ops.claude_cli import (
    ClaudeCliError,
    claude_mcp_add,
    has_claude_cli,
)

MANAGED_SECTION_START = "<!-- LV_DCP-managed-section:start:v1 -->"
MANAGED_SECTION_END = "<!-- LV_DCP-managed-section:end:v1 -->"
VERSION_MARKER_PREFIX = "lvdcp-managed-version:"


def _managed_block(version: str) -> str:
    return f"""{MANAGED_SECTION_START}
<!-- {VERSION_MARKER_PREFIX} {version} -->
<!-- This section is managed by `ctx mcp install`. Remove with `ctx mcp uninstall`. -->

## LV_DCP context discipline

When working in a Python project that has `.context/cache.db` at its root
(a project indexed by LV_DCP), your default is to call the `lvdcp_pack`
MCP tool **before** reading multiple files to understand the codebase.

- For questions of the form "how does X work", "where is Y", "what does Z do":
  call `lvdcp_pack(path=<project_root>, query=<user's question>, mode="navigate")`.
- For edit tasks ("change X", "add Y", "fix Z"):
  call `lvdcp_pack(path=<project_root>, query=<task description>, mode="edit")`.

The returned `markdown` field is 2-20 KB of ranked relevant files and
symbols pulled from a pre-built index. Reading this pack replaces a
repo-wide `grep` or reading many files blind.

If the pack's `coverage` field is `ambiguous`, either expand `limit`,
rephrase the query with more specific keywords, or ask the user to
clarify — do not proceed with a low-confidence pack on edit tasks.

If `lvdcp_pack` returns an error containing `not_indexed`, call `lvdcp_scan(path)` first.

This discipline does not apply to: trivial single-file tasks, syntax-only
questions, or projects without `.context/cache.db`.

{MANAGED_SECTION_END}
"""


@dataclass(frozen=True)
class InstallResult:
    entry_command: str
    entry_args: list[str] = field(default_factory=list)
    scope: str = "user"
    claudemd_path: Path = field(default_factory=Path)
    config_path: Path = field(default_factory=Path)
    config_created: bool = False
    version: str = ""


def _write_managed_section(claudemd_path: Path, version: str) -> None:
    if claudemd_path.exists():
        content = claudemd_path.read_text(encoding="utf-8")
    else:
        content = ""
        claudemd_path.parent.mkdir(parents=True, exist_ok=True)

    new_block = _managed_block(version).strip()

    if MANAGED_SECTION_START in content:
        start = content.index(MANAGED_SECTION_START)
        try:
            end = content.index(MANAGED_SECTION_END, start) + len(MANAGED_SECTION_END)
        except ValueError:
            # START marker present but END missing (truncated / hand-edited file).
            # Treat the rest of the file from the start marker as the stale section
            # and replace it entirely.
            end = len(content)
        new_content = content[:start] + new_block + content[end:]
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n" + new_block + "\n"

    claudemd_path.write_text(new_content, encoding="utf-8")


def _bootstrap_config(config_path: Path) -> bool:
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "projects": []}
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return True


def install_lvdcp(  # noqa: PLR0913
    *,
    claudemd_path: Path,
    config_path: Path,
    entry_command: str,
    entry_args: list[str],
    scope: str,
    version: str,
) -> InstallResult:
    """Install lvdcp MCP server + supporting files.

    Raises ClaudeCliError if the `claude` CLI is missing or `claude mcp add` fails.
    """
    if not has_claude_cli():
        raise ClaudeCliError(
            "claude CLI not found on PATH. Install Claude Code first "
            "(https://docs.claude.com/claude-code) or run `ctx mcp install --dry-run` "
            "to print a JSON snippet for manual copy into ~/.claude.json."
        )

    claude_mcp_add(
        server_name="lvdcp",
        command=entry_command,
        args=entry_args,
        scope=scope,
    )

    config_created = _bootstrap_config(config_path)
    _write_managed_section(claudemd_path, version)

    return InstallResult(
        entry_command=entry_command,
        entry_args=list(entry_args),
        scope=scope,
        claudemd_path=claudemd_path,
        config_path=config_path,
        config_created=config_created,
        version=version,
    )


def build_dry_run_snippet(
    *,
    server_name: str,
    command: str,
    args: list[str],
    scope: str,
) -> str:
    """Return a JSON snippet the user can copy into ~/.claude.json manually."""
    payload = {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
            }
        }
    }
    return json.dumps(payload, indent=2)
