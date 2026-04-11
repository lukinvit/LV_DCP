"""High-level `ctx mcp uninstall` implementation."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

from libs.mcp_ops.claude_cli import ClaudeCliError, claude_mcp_remove
from libs.mcp_ops.install import MANAGED_SECTION_END, MANAGED_SECTION_START


@dataclass(frozen=True)
class LegacyCleanResult:
    removed: bool


def _strip_managed_section(claudemd_path: Path) -> None:
    if not claudemd_path.exists():
        return
    content = claudemd_path.read_text(encoding="utf-8")
    if MANAGED_SECTION_START not in content:
        return
    start = content.index(MANAGED_SECTION_START)
    end = content.index(MANAGED_SECTION_END, start) + len(MANAGED_SECTION_END)
    while end < len(content) and content[end] == "\n":
        end += 1
    while start > 0 and content[start - 1] == "\n":
        start -= 1
    new_content = content[:start].rstrip("\n") + "\n" + content[end:]
    if not new_content.strip():
        new_content = ""
    claudemd_path.write_text(new_content, encoding="utf-8")


def uninstall_lvdcp(
    *,
    claudemd_path: Path,
    scope: str,
) -> None:
    """Remove lvdcp MCP registration and managed CLAUDE.md section.

    Tolerates `claude mcp remove` errors (e.g. server not registered). Local
    file cleanup proceeds regardless.
    """
    with contextlib.suppress(ClaudeCliError):
        claude_mcp_remove(server_name="lvdcp", scope=scope)
    _strip_managed_section(claudemd_path)


def clean_legacy_settings_json(settings_path: Path) -> LegacyCleanResult:
    """Remove stray `mcpServers.lvdcp` key from ~/.claude/settings.json.

    Old broken `ctx mcp install` wrote the lvdcp server entry into this file.
    settings.json is actually the permissions file — `mcpServers` there does
    nothing but pollute. Scrub it.
    """
    if not settings_path.exists():
        return LegacyCleanResult(removed=False)

    raw = settings_path.read_text(encoding="utf-8")
    try:
        data: dict[str, object] = json.loads(raw)
    except json.JSONDecodeError:
        return LegacyCleanResult(removed=False)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or "lvdcp" not in servers:
        return LegacyCleanResult(removed=False)

    servers.pop("lvdcp", None)
    if not servers:
        data.pop("mcpServers", None)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return LegacyCleanResult(removed=True)
