"""Probe the LV_DCP daemon status via launchctl list."""

from __future__ import annotations

import subprocess

from libs.mcp_ops.launchd import LAUNCH_AGENT_LABEL
from libs.status.models import DaemonStatus


def probe_daemon() -> DaemonStatus:
    """Return DaemonStatus based on `launchctl list tech.lvdcp.agent`.

    Exit 0 = running, exit 113 = not loaded, other = error.
    FileNotFoundError (non-macOS or launchctl missing) = error.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            ["launchctl", "list", LAUNCH_AGENT_LABEL],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except FileNotFoundError:
        return DaemonStatus(state="error", detail="launchctl not found on PATH (not macOS?)")

    if proc.returncode == 0:
        return DaemonStatus(state="running", detail="loaded and active")
    if proc.returncode == 113:
        return DaemonStatus(
            state="not_loaded",
            detail="service not loaded — run `ctx watch install-service`",
        )
    return DaemonStatus(state="error", detail=(proc.stderr or "").strip())
