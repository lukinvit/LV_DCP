"""ctx mcp-install — append managed CLAUDE.md section + write MCP settings."""

from __future__ import annotations

import json
import time
from pathlib import Path

CLAUDEMD_SENTINEL_START = "<!-- LV_DCP-managed-section:start:v1 -->"
CLAUDEMD_SENTINEL_END = "<!-- LV_DCP-managed-section:end:v1 -->"

MANAGED_BLOCK = f"""{CLAUDEMD_SENTINEL_START}
<!-- This section is managed by `ctx mcp-install`. Edit via `ctx mcp-install --reconfigure` or remove with `ctx mcp-uninstall`. -->

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

{CLAUDEMD_SENTINEL_END}
"""


def install_claudemd_section(claudemd_path: Path) -> None:
    """Inject the managed section into a CLAUDE.md file, with backup and idempotency."""
    if claudemd_path.exists():
        content = claudemd_path.read_text(encoding="utf-8")
        # Always back up existing file
        timestamp = int(time.time())
        backup_path = claudemd_path.parent / f"{claudemd_path.name}.lvdcp-backup-{timestamp}"
        backup_path.write_text(content, encoding="utf-8")
    else:
        content = ""
        claudemd_path.parent.mkdir(parents=True, exist_ok=True)

    if CLAUDEMD_SENTINEL_START in content:
        # Replace existing managed block
        start = content.index(CLAUDEMD_SENTINEL_START)
        end_marker = content.index(CLAUDEMD_SENTINEL_END, start)
        end = end_marker + len(CLAUDEMD_SENTINEL_END)
        new_content = content[:start] + MANAGED_BLOCK.strip() + content[end:]
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n" + MANAGED_BLOCK

    claudemd_path.write_text(new_content, encoding="utf-8")


def uninstall_claudemd_section(claudemd_path: Path) -> None:
    """Remove the managed section from CLAUDE.md, leaving other content intact."""
    if not claudemd_path.exists():
        return
    content = claudemd_path.read_text(encoding="utf-8")
    if CLAUDEMD_SENTINEL_START not in content:
        return
    start = content.index(CLAUDEMD_SENTINEL_START)
    end_marker = content.index(CLAUDEMD_SENTINEL_END, start)
    end = end_marker + len(CLAUDEMD_SENTINEL_END)
    # Also strip surrounding blank lines
    while start > 0 and content[start - 1] == "\n":
        start -= 1
    while end < len(content) and content[end] == "\n":
        end += 1
    new_content = (
        content[:start]
        + ("\n" if content[:start] and not content[:start].endswith("\n") else "")
        + content[end:]
    )
    claudemd_path.write_text(new_content, encoding="utf-8")


def install_mcp_settings(settings_path: Path, *, entry_point: str) -> None:
    """Add the lvdcp MCP server entry to a Claude settings.json file."""
    if settings_path.exists():
        data: dict[str, object] = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        data = {}
        settings_path.parent.mkdir(parents=True, exist_ok=True)

    servers: dict[str, object] = data.setdefault("mcpServers", {})  # type: ignore[assignment]
    # Split entry_point into command + args
    parts = entry_point.split()
    servers["lvdcp"] = {
        "command": parts[0],
        "args": parts[1:],
    }

    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def uninstall_mcp_settings(settings_path: Path) -> None:
    """Remove the lvdcp entry from mcpServers without touching other keys."""
    if not settings_path.exists():
        return
    data: dict[str, object] = json.loads(settings_path.read_text(encoding="utf-8"))
    servers: dict[str, object] = data.get("mcpServers", {})  # type: ignore[assignment]
    servers.pop("lvdcp", None)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
