"""launchctl wrappers for the LV_DCP daemon service.

macOS-only. Runs `launchctl bootstrap gui/<uid> <plist>` (install) and
`launchctl bootout gui/<uid>/<label>` (uninstall). Requires an active GUI
session because gui/<uid> is not reachable from headless SSH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


BREADCRUMB_PRUNE_LABEL = "com.lukinvit.lvdcp.breadcrumb-prune"

_BREADCRUMB_PRUNE_TMPL = (
    Path(__file__).resolve().parents[2]
    / "deploy" / "launchd" / "com.lukinvit.lvdcp.breadcrumb-prune.plist.tmpl"
)


def write_breadcrumb_prune_plist(*, plist_path: Path, ctx_path: Path) -> Path:
    """Render and write the breadcrumb-prune launchd plist."""
    log_dir = Path.home() / "Library" / "Logs" / "lvdcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    template = _BREADCRUMB_PRUNE_TMPL.read_text(encoding="utf-8")
    rendered = template.replace("{{CTX_PATH}}", str(ctx_path)).replace("{{LOG_DIR}}", str(log_dir))
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(rendered, encoding="utf-8")
    return plist_path


def bootstrap_breadcrumb_prune() -> None:
    """Install + load the breadcrumb-prune launchd entry for the current GUI user."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{BREADCRUMB_PRUNE_LABEL}.plist"
    ctx_path_str = shutil.which("ctx") or sys.executable
    write_breadcrumb_prune_plist(plist_path=plist_path, ctx_path=Path(ctx_path_str))
    uid = os.getuid()
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)], check=False)  # noqa: S603 S607


def bootout_breadcrumb_prune() -> None:
    """Unload and remove the breadcrumb-prune launchd entry (idempotent)."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{BREADCRUMB_PRUNE_LABEL}.plist"
    if not plist_path.exists():
        return
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], check=False)  # noqa: S603 S607
    plist_path.unlink(missing_ok=True)
