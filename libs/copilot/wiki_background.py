"""Background wiki refresh primitives for the Project Copilot Wrapper.

The in-process ``refresh_wiki`` path makes synchronous LLM calls; on a
large project that blocks the caller for minutes. This module spawns a
detached subprocess so ``ctx project refresh --wiki-background`` returns
immediately and the wiki rebuilds out-of-band.

Design notes
------------

- **Subprocess, not thread** — a threading.Thread dies when the parent
  CLI process exits, so ``ctx`` would have to stay alive to finish the
  wiki. A detached ``subprocess.Popen`` survives terminal close.
- **Lock file as the only IPC** — the runner writes ``.context/wiki/.refresh.lock``
  as JSON ``{"pid", "started_at"}`` before doing work and unlinks it on
  exit. ``is_refresh_in_progress`` simply checks the lock and validates
  the PID. No sockets, no tempdirs, no daemon threads.
- **Stale-lock handling** — if the lock exists but the PID is dead, we
  treat the refresh as finished (crashed). A lock older than
  ``_STALE_LOCK_AFTER_SECONDS`` is also ignored so a zombie runner cannot
  wedge the copilot forever.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


LOCK_FILENAME = ".refresh.lock"
LOG_FILENAME = ".refresh.log"
_STALE_LOCK_AFTER_SECONDS = 60 * 60  # 1h ceiling for a single wiki refresh


@dataclass(frozen=True, slots=True)
class BackgroundRefreshStatus:
    """Lightweight snapshot of a (possibly) running background refresh."""

    in_progress: bool
    pid: int | None
    started_at: float | None
    lock_path: Path | None
    stale: bool = False


def _lock_path(root: Path) -> Path:
    return root / ".context" / "wiki" / LOCK_FILENAME


def _log_path(root: Path) -> Path:
    return root / ".context" / "wiki" / LOG_FILENAME


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* exists. POSIX-only (LV_DCP is macOS-first)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Another user owns the PID — treat as alive (conservative).
        return True
    return True


def read_status(root: Path) -> BackgroundRefreshStatus:
    """Inspect ``.context/wiki/.refresh.lock`` without mutating it.

    Returns a snapshot. ``in_progress=False`` covers three shapes:

    - no lock file at all;
    - lock exists but PID is dead (``stale=True``, crashed runner);
    - lock is older than 1h (``stale=True``, zombie).
    """
    lock = _lock_path(root)
    if not lock.exists():
        return BackgroundRefreshStatus(in_progress=False, pid=None, started_at=None, lock_path=None)
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt lock → treat as stale; caller may choose to unlink.
        log.warning("wiki refresh lock is corrupt at %s", lock, exc_info=True)
        return BackgroundRefreshStatus(
            in_progress=False, pid=None, started_at=None, lock_path=lock, stale=True
        )

    pid = int(payload.get("pid", 0)) or None
    started_at = float(payload.get("started_at", 0.0)) or None
    age = (time.time() - started_at) if started_at else 0.0
    stale = bool(
        (pid is not None and not _pid_alive(pid))
        or (started_at is not None and age > _STALE_LOCK_AFTER_SECONDS)
    )
    return BackgroundRefreshStatus(
        in_progress=not stale,
        pid=pid,
        started_at=started_at,
        lock_path=lock,
        stale=stale,
    )


def start_background_refresh(
    root: Path,
    *,
    all_modules: bool = False,
    _popen: type[subprocess.Popen[bytes]] | None = None,
) -> BackgroundRefreshStatus:
    """Spawn a detached wiki-refresh subprocess. Return immediately.

    Idempotent: if a healthy refresh is already running, return its
    existing status instead of launching a second one. Stale locks are
    cleared before spawning.

    ``_popen`` is a test hook so unit tests can swap in a stub without
    actually forking a process.
    """
    root = root.resolve()
    wiki_dir = root / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    current = read_status(root)
    if current.in_progress:
        return current
    if current.stale and current.lock_path is not None:
        # Clean up before relaunching.
        with contextlib.suppress(FileNotFoundError):
            current.lock_path.unlink()

    popen_cls: type[subprocess.Popen[bytes]] = _popen if _popen is not None else subprocess.Popen  # type: ignore[assignment]
    # The log file handle is intentionally not closed here: ownership
    # transfers to the child process via ``stdout=log_fh``. Closing it in
    # the parent would truncate the child's writes on some platforms.
    log_fh = _log_path(root).open("ab")
    args: list[str] = [
        sys.executable,
        "-m",
        "libs.copilot._wiki_bg_runner",
        str(root),
    ]
    if all_modules:
        args.append("--all")

    proc = popen_cls(
        args,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    pid = int(getattr(proc, "pid", 0)) or None
    started_at = time.time()

    # The runner itself also writes the lock (race-safe), but we write it
    # eagerly here so that a caller's immediate ``is_refresh_in_progress``
    # sees the refresh even if the child hasn't started yet.
    lock_payload = {
        "pid": pid,
        "started_at": started_at,
        "all_modules": all_modules,
    }
    _lock_path(root).write_text(json.dumps(lock_payload), encoding="utf-8")
    return BackgroundRefreshStatus(
        in_progress=True,
        pid=pid,
        started_at=started_at,
        lock_path=_lock_path(root),
    )


def is_refresh_in_progress(root: Path) -> bool:
    """Convenience boolean wrapper around :func:`read_status`."""
    return read_status(root).in_progress
