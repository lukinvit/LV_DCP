"""Detached runner invoked via ``python -m libs.copilot._wiki_bg_runner``.

The parent process (``ctx project refresh --wiki-background``) spawns
this module with ``subprocess.Popen`` and exits immediately. The runner:

1. writes ``.context/wiki/.refresh.lock`` with its own PID;
2. installs a SIGTERM handler so ``ctx project wiki --stop`` can ask it
   to exit gracefully without leaving a stale lock behind;
3. calls the reduced wiki-update pipeline synchronously, streaming
   per-module progress back into the lock file via
   :func:`libs.copilot.wiki_background.write_progress`;
4. unlinks the lock on exit (success, failure, or SIGTERM).

All stdout/stderr is redirected by the parent to
``.context/wiki/.refresh.log`` so the user can always inspect what
happened after the fact.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from types import FrameType

#: Maximum number of ``.refresh.log`` lines returned to the writer. The
#: persistence layer applies its own cap via ``_MAX_LOG_TAIL_LINES``; we
#: use a generous multiple here so we can discard blank/boilerplate lines
#: during post-processing without risking truncation of useful context.
_LOG_TAIL_READ_CAP = 200


def _lock_path(root: Path) -> Path:
    return root / ".context" / "wiki" / ".refresh.lock"


def _log_path(root: Path) -> Path:
    return root / ".context" / "wiki" / ".refresh.log"


def _initial_log_offset(root: Path) -> int:
    """Byte offset in ``.refresh.log`` at runner startup.

    The parent redirects stdout/stderr of the runner into this file via
    ``>>`` semantics (``open("ab")``), so earlier runs' lines are still
    present. We remember the starting size so a post-mortem tail only
    surfaces lines from *this* run.
    """
    path = _log_path(root)
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _capture_log_tail(
    root: Path, *, start_offset: int, max_lines: int = _LOG_TAIL_READ_CAP
) -> list[str] | None:
    """Return the last ``max_lines`` of ``.refresh.log`` since ``start_offset``.

    Returns ``None`` when the log file doesn't exist (e.g. unit-test
    environments that don't spawn a real subprocess with stdout
    redirection). Any read error also returns ``None`` — this is a
    best-effort diagnostic, never a failure mode for the runner.
    """
    path = _log_path(root)
    try:
        # Flush any pending logging-handler writes before tailing.
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):  # pragma: no cover — best-effort
                stream.flush()
        with path.open("rb") as fh:
            fh.seek(start_offset)
            raw = fh.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    lines = [line.rstrip("\r") for line in text.split("\n") if line.strip()]
    if not lines:
        return None
    return lines[-max_lines:]


def _write_initial_lock(root: Path, *, all_modules: bool) -> None:
    lock = _lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.time(),
                "all_modules": all_modules,
                "phase": "starting",
            }
        ),
        encoding="utf-8",
    )


def _clear_lock(root: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        _lock_path(root).unlink()


def _install_sigterm_handler() -> None:
    """Convert SIGTERM to SystemExit so ``finally`` blocks run.

    The default SIGTERM handler terminates the process immediately
    without unwinding — meaning ``finally: _clear_lock(root)`` would
    never execute and the lock would be left behind for the 1-hour
    stale-timeout to reap. Raising ``SystemExit`` from the handler
    lets Python unwind normally.
    """

    def _handle(signum: int, _frame: FrameType | None) -> None:  # pragma: no cover — signal path
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lvdcp-wiki-bg")
    parser.add_argument("root", type=Path)
    parser.add_argument("--all", action="store_true", dest="all_modules")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [bg-wiki pid=%(process)d] %(message)s",
    )
    log = logging.getLogger("lvdcp.wiki_bg")

    _write_initial_lock(root, all_modules=args.all_modules)
    _install_sigterm_handler()
    # Capture the log file size *before* our first log line so the
    # post-mortem tail only includes output from this run (``.refresh.log``
    # is append-only and accumulates across refreshes).
    log_start_offset = _initial_log_offset(root)
    log.info("start root=%s all_modules=%s", root, args.all_modules)
    exit_code = 0
    # ``modules_updated`` reflects modules actually refreshed before exit.
    # For clean runs it equals the return value of
    # ``_run_wiki_update_in_process``; for SIGTERM/crash it's the count
    # reported by the last progress callback, so the user sees
    # "got through 3/12" instead of a silent partial.
    modules_updated = 0
    started_at = time.time()
    try:
        # Deferred imports: pulling in `orchestrator` brings the full
        # scanning stack; keeping them lazy makes
        # ``python -m libs.copilot._wiki_bg_runner --help`` cheap.
        from libs.copilot.orchestrator import _run_wiki_update_in_process  # noqa: PLC0415
        from libs.copilot.wiki_background import (  # noqa: PLC0415
            PHASE_FINALIZING,
            PHASE_GENERATING,
            PHASE_LOADING,
            write_progress,
        )

        write_progress(root, phase=PHASE_LOADING)

        def _on_progress(
            *, done: int, total: int, current: str | None, phase: str = PHASE_GENERATING
        ) -> None:
            nonlocal modules_updated
            modules_updated = done
            write_progress(
                root,
                phase=phase,
                modules_total=total,
                modules_done=done,
                current_module=current,
            )

        updated, messages = _run_wiki_update_in_process(
            root,
            all_modules=args.all_modules,
            on_progress=_on_progress,
        )
        modules_updated = max(modules_updated, int(updated))
        write_progress(root, phase=PHASE_FINALIZING)
        log.info("done updated=%s messages=%s", updated, messages)
    except SystemExit as exc:
        log.info("wiki refresh cancelled via signal (exit=%s)", exc.code)
        exit_code = int(exc.code) if isinstance(exc.code, int) else 143
    except Exception:  # pragma: no cover — surface full trace in the log file
        log.error("wiki refresh crashed:\n%s", traceback.format_exc())
        exit_code = 1
    finally:
        # ``write_last_refresh`` must succeed even if the happy-path
        # imports failed (e.g. syntax error in orchestrator); re-import
        # defensively here.
        try:
            from libs.copilot.wiki_background import (  # noqa: PLC0415
                write_last_refresh as _write_last_refresh,
            )

            # Only capture the log tail on crashes. Clean exit (0) and
            # SIGTERM (143) don't need it — the user gets a successful
            # summary or an explicit "cancelled" label instead, and an
            # unused log tail just bloats the record.
            log_tail: list[str] | None = None
            if exit_code not in (0, 143):
                log_tail = _capture_log_tail(root, start_offset=log_start_offset)

            _write_last_refresh(
                root,
                exit_code=exit_code,
                modules_updated=modules_updated,
                elapsed_seconds=max(0.0, time.time() - started_at),
                log_tail=log_tail,
            )
        except Exception:  # pragma: no cover — best-effort persistence
            log.error("failed to write .refresh.last:\n%s", traceback.format_exc())
        _clear_lock(root)
    return exit_code


if __name__ == "__main__":  # pragma: no cover — entrypoint
    sys.exit(main())
