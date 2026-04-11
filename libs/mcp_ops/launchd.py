"""launchctl wrappers for the LV_DCP daemon service.

macOS-only. Runs `launchctl bootstrap gui/<uid> <plist>` (install) and
`launchctl bootout gui/<uid>/<label>` (uninstall). Requires an active GUI
session because gui/<uid> is not reachable from headless SSH.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Layering exception: libs/ normally does not depend on apps/. We reuse the
# existing plist generator in apps/agent/plist.py instead of duplicating it
# here. The plist generator is a pure string builder with no runtime
# coupling to the agent, so the inversion is safe and intentional.
from apps.agent.plist import generate_plist

LAUNCH_AGENT_LABEL = "tech.lvdcp.agent"
DEFAULT_TIMEOUT_SECONDS = 10.0


class LaunchctlError(Exception):
    """Raised when `launchctl` returns a non-zero exit."""


def write_plist(
    *,
    target_path: Path,
    program_arguments: list[str],
    log_dir: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    content = generate_plist(
        label=LAUNCH_AGENT_LABEL,
        program_arguments=program_arguments,
        log_dir=log_dir,
    )
    target_path.write_text(content, encoding="utf-8")
    target_path.chmod(0o644)


def bootstrap_agent(*, plist_path: Path, uid: int) -> None:
    cmd = ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)]
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        raise LaunchctlError(
            f"launchctl bootstrap failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )


def bootout_agent(*, uid: int) -> None:
    cmd = ["launchctl", "bootout", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"]
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        raise LaunchctlError(
            f"launchctl bootout failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
