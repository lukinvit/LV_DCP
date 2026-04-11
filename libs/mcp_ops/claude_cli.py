"""Subprocess wrappers around the `claude` CLI.

We delegate MCP server registration to `claude mcp add/remove/list` rather
than writing ~/.claude.json directly — avoids corrupting a file that
Claude Code may hold open.
"""

from __future__ import annotations

import shutil
import subprocess

CLAUDE_BIN = "claude"
DEFAULT_TIMEOUT_SECONDS = 10.0


class ClaudeCliError(Exception):
    """Raised when the `claude` CLI is missing or returns a non-zero exit."""


def has_claude_cli() -> bool:
    """Return True if the `claude` binary is discoverable on PATH."""
    return shutil.which(CLAUDE_BIN) is not None


def claude_mcp_add(
    *,
    server_name: str,
    command: str,
    args: list[str],
    scope: str,
) -> None:
    """Invoke `claude mcp add --scope <scope> <name> -- <command> <args...>`.

    Raises ClaudeCliError on non-zero exit or missing binary.
    """
    cmd = [
        CLAUDE_BIN,
        "mcp",
        "add",
        "--scope",
        scope,
        server_name,
        "--",
        command,
        *args,
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClaudeCliError(
            f"claude CLI not found on PATH; install Claude Code first ({exc})"
        ) from exc
    if proc.returncode != 0:
        raise ClaudeCliError(
            f"claude mcp add failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )


def claude_mcp_remove(*, server_name: str, scope: str) -> None:
    """Invoke `claude mcp remove --scope <scope> <name>`."""
    cmd = [CLAUDE_BIN, "mcp", "remove", "--scope", scope, server_name]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClaudeCliError(f"claude CLI not found on PATH ({exc})") from exc
    if proc.returncode != 0:
        raise ClaudeCliError(
            f"claude mcp remove failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )


def claude_mcp_list() -> str:
    """Invoke `claude mcp list` and return raw stdout."""
    cmd = [CLAUDE_BIN, "mcp", "list"]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClaudeCliError(f"claude CLI not found on PATH ({exc})") from exc
    if proc.returncode != 0:
        raise ClaudeCliError(
            f"claude mcp list failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout
