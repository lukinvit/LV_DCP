"""Background worker that syncs a project to its Obsidian vault, debounced.

Called by the daemon after each scan. Guards against running more often than
``config.debounce_seconds`` by persisting the last-run timestamp to
``.context/obsidian_last_sync``. Delegates actual work to ``ctx obsidian sync``
so the worker stays thin and re-uses all CLI-tested pathways. Never raises —
errors are logged and suppressed so a single bad sync doesn't kill the daemon.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

from libs.core.projects_config import ObsidianConfig

_OBSIDIAN_MARKER = "obsidian_last_sync"
_log = logging.getLogger(__name__)


def run_obsidian_sync(project_root: Path, config: ObsidianConfig) -> bool:
    """Sync `project_root` to its Obsidian vault if debounce window has elapsed.

    Returns True iff a sync was performed. Returns False if disabled, debounced,
    or if the sync raised/exited non-zero. Never raises.
    """
    if not config.enabled or not config.vault_path:
        return False

    ctx_dir = project_root / ".context"
    marker = ctx_dir / _OBSIDIAN_MARKER
    now = time.time()

    if marker.exists():
        try:
            last_ts = float(marker.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            last_ts = 0.0
        if now - last_ts < config.debounce_seconds:
            return False

    try:
        subprocess.run(  # noqa: S603  # controlled invocation of our own CLI
            [
                sys.executable,
                "-m",
                "apps.cli.main",
                "obsidian",
                "sync",
                str(project_root),
                "--vault",
                config.vault_path,
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        _log.exception("obsidian_worker: sync failed for %s", project_root)
        return False

    ctx_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(now), encoding="utf-8")
    return True
