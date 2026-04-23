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
  as JSON ``{"pid", "started_at", "all_modules", "phase",
  "modules_total", "modules_done", "current_module"}`` before doing work
  and unlinks it on exit. ``is_refresh_in_progress`` simply checks the
  lock and validates the PID. No sockets, no tempdirs, no daemon threads.
- **Progress is best-effort** — the runner rewrites the lock on every
  module boundary. Readers see an eventually-consistent snapshot; a
  mid-write read may see the previous payload but never a corrupt one
  (we write-then-rename).
- **Stale-lock handling** — if the lock exists but the PID is dead, we
  treat the refresh as finished (crashed). A lock older than
  ``_STALE_LOCK_AFTER_SECONDS`` is also ignored so a zombie runner cannot
  wedge the copilot forever.
- **Cancellation** — :func:`cancel_background_refresh` sends SIGTERM to
  the runner. The runner installs a handler that raises ``SystemExit``,
  which lets its ``finally`` block unlink the lock before the process
  dies.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


LOCK_FILENAME = ".refresh.lock"
LOG_FILENAME = ".refresh.log"
LAST_REFRESH_FILENAME = ".refresh.last"
_STALE_LOCK_AFTER_SECONDS = 60 * 60  # 1h ceiling for a single wiki refresh

#: Maximum number of log lines persisted into ``.refresh.last``. Bounded
#: to keep the record small (it's read on every ``ctx project check``)
#: while still carrying enough context to triage a crash.
_MAX_LOG_TAIL_LINES = 20

# Canonical phase labels emitted by the runner.
PHASE_STARTING = "starting"
PHASE_LOADING = "loading"
PHASE_GENERATING = "generating"
PHASE_FINALIZING = "finalizing"


@dataclass(frozen=True, slots=True)
class LastRefreshRecord:
    """Outcome of the most recent background refresh.

    Written by the runner's ``finally`` block so it captures all three
    exit shapes: clean completion (``exit_code == 0``), SIGTERM
    cancellation (``exit_code == 143``), and crashes (any other
    non-zero). ``modules_updated`` is the count the runner got through
    before it exited — for crashes this may be less than
    ``modules_total``.

    ``log_tail`` is populated only on crash (non-zero, non-SIGTERM).
    It carries the last ~20 lines of ``.refresh.log`` as captured at
    runner exit time — self-contained so the user can diagnose without
    re-reading the log file (which accumulates across runs).
    """

    completed_at: float
    exit_code: int
    modules_updated: int
    elapsed_seconds: float
    log_tail: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class BackgroundRefreshStatus:
    """Lightweight snapshot of a (possibly) running background refresh."""

    in_progress: bool
    pid: int | None
    started_at: float | None
    lock_path: Path | None
    stale: bool = False
    phase: str | None = None
    modules_total: int | None = None
    modules_done: int = 0
    current_module: str | None = None
    last_run: LastRefreshRecord | None = None


def _lock_path(root: Path) -> Path:
    return root / ".context" / "wiki" / LOCK_FILENAME


def _log_path(root: Path) -> Path:
    return root / ".context" / "wiki" / LOG_FILENAME


def _last_refresh_path(root: Path) -> Path:
    return root / ".context" / "wiki" / LAST_REFRESH_FILENAME


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


def _atomic_write_lock(lock: Path, payload: dict[str, Any]) -> None:
    """Write-then-rename so a concurrent reader never sees a torn file."""
    tmp = lock.with_suffix(lock.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(lock)


def write_last_refresh(  # noqa: PLR0913 — kw-only payload fields; constructor-style
    root: Path,
    *,
    exit_code: int,
    modules_updated: int,
    elapsed_seconds: float,
    completed_at: float | None = None,
    log_tail: Sequence[str] | None = None,
) -> None:
    """Persist the outcome of the most recent refresh to ``.refresh.last``.

    Called from the runner's ``finally`` block so it captures clean
    completion, SIGTERM cancellation, and crashes. Uses the same
    write-then-rename pattern as the lock so a concurrent ``ctx project
    check`` never sees a torn file.

    ``log_tail`` is truncated to the last :data:`_MAX_LOG_TAIL_LINES`
    entries before persistence; callers can pass a larger list and rely
    on the bound.
    """
    path = _last_refresh_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "completed_at": float(completed_at if completed_at is not None else time.time()),
        "exit_code": int(exit_code),
        "modules_updated": int(modules_updated),
        "elapsed_seconds": float(elapsed_seconds),
    }
    if log_tail:
        trimmed = [str(line) for line in list(log_tail)[-_MAX_LOG_TAIL_LINES:]]
        payload["log_tail"] = trimmed
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def read_last_refresh(root: Path) -> LastRefreshRecord | None:
    """Read ``.refresh.last`` if it exists. Returns ``None`` otherwise.

    A corrupt file is treated the same as a missing one: we simply have
    no record of the last run. That's a UX degradation, not a bug — the
    next refresh rewrites the file.
    """
    path = _last_refresh_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("wiki last-refresh record is corrupt at %s", path, exc_info=True)
        return None
    try:
        raw_tail = payload.get("log_tail")
        log_tail: tuple[str, ...] | None = None
        if isinstance(raw_tail, list) and raw_tail:
            log_tail = tuple(str(line) for line in raw_tail)
        return LastRefreshRecord(
            completed_at=float(payload["completed_at"]),
            exit_code=int(payload["exit_code"]),
            modules_updated=int(payload["modules_updated"]),
            elapsed_seconds=float(payload["elapsed_seconds"]),
            log_tail=log_tail,
        )
    except (KeyError, TypeError, ValueError):
        log.warning("wiki last-refresh record is malformed at %s", path, exc_info=True)
        return None


def read_status(root: Path) -> BackgroundRefreshStatus:
    """Inspect ``.context/wiki/.refresh.lock`` without mutating it.

    Returns a snapshot. ``in_progress=False`` covers three shapes:

    - no lock file at all;
    - lock exists but PID is dead (``stale=True``, crashed runner);
    - lock is older than 1h (``stale=True``, zombie).
    """
    lock = _lock_path(root)
    last_run = read_last_refresh(root)
    if not lock.exists():
        return BackgroundRefreshStatus(
            in_progress=False,
            pid=None,
            started_at=None,
            lock_path=None,
            last_run=last_run,
        )
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt lock → treat as stale; caller may choose to unlink.
        log.warning("wiki refresh lock is corrupt at %s", lock, exc_info=True)
        return BackgroundRefreshStatus(
            in_progress=False,
            pid=None,
            started_at=None,
            lock_path=lock,
            stale=True,
            last_run=last_run,
        )

    pid = int(payload.get("pid", 0)) or None
    started_at = float(payload.get("started_at", 0.0)) or None
    age = (time.time() - started_at) if started_at else 0.0
    stale = bool(
        (pid is not None and not _pid_alive(pid))
        or (started_at is not None and age > _STALE_LOCK_AFTER_SECONDS)
    )
    phase = payload.get("phase") or None
    raw_total = payload.get("modules_total")
    modules_total = int(raw_total) if isinstance(raw_total, int) and raw_total >= 0 else None
    modules_done = int(payload.get("modules_done", 0) or 0)
    current_module = payload.get("current_module") or None
    return BackgroundRefreshStatus(
        in_progress=not stale,
        pid=pid,
        started_at=started_at,
        lock_path=lock,
        stale=stale,
        phase=phase,
        modules_total=modules_total,
        modules_done=modules_done,
        current_module=current_module,
        last_run=last_run,
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
        "phase": PHASE_STARTING,
    }
    _atomic_write_lock(_lock_path(root), lock_payload)
    return BackgroundRefreshStatus(
        in_progress=True,
        pid=pid,
        started_at=started_at,
        lock_path=_lock_path(root),
        phase=PHASE_STARTING,
    )


def write_progress(
    root: Path,
    *,
    phase: str,
    modules_total: int | None = None,
    modules_done: int | None = None,
    current_module: str | None = None,
) -> None:
    """Merge-update the lock file with fresh progress fields.

    Invoked by the runner at every module boundary. A read-modify-write
    race is acceptable here: the runner is the only writer for
    progress fields; the parent only writes the lock once (eagerly) at
    spawn time. Stale reads remain valid — they just lag by one module.
    """
    lock = _lock_path(root)
    payload: dict[str, Any] = {}
    if lock.exists():
        try:
            payload = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover — corrupt lock is handled by read_status
            payload = {}
    payload["phase"] = phase
    if modules_total is not None:
        payload["modules_total"] = modules_total
    if modules_done is not None:
        payload["modules_done"] = modules_done
    # ``current_module=None`` is a legitimate reset (e.g. after the last
    # module has finished), so we rewrite it unconditionally.
    payload["current_module"] = current_module
    _atomic_write_lock(lock, payload)


def cancel_background_refresh(root: Path) -> BackgroundRefreshStatus:
    """Send SIGTERM to the running refresh, if any.

    Returns the status observed just before sending the signal so the
    caller can render a meaningful "cancelled PID X" message. A
    non-running or stale refresh is a no-op (the lock is cleared as a
    side-effect so the next :func:`start_background_refresh` starts
    clean).
    """
    status = read_status(root)
    if not status.in_progress or status.pid is None:
        if status.stale and status.lock_path is not None:
            with contextlib.suppress(FileNotFoundError):
                status.lock_path.unlink()
        return status
    try:
        os.kill(status.pid, signal.SIGTERM)
    except ProcessLookupError:
        # Race: process died between read and kill. Clean up the lock.
        if status.lock_path is not None:
            with contextlib.suppress(FileNotFoundError):
                status.lock_path.unlink()
    return status


def is_refresh_in_progress(root: Path) -> bool:
    """Convenience boolean wrapper around :func:`read_status`."""
    return read_status(root).in_progress
