"""Detached runner invoked via ``python -m libs.copilot._wiki_bg_runner``.

The parent process (``ctx project refresh --wiki-background``) spawns
this module with ``subprocess.Popen`` and exits immediately. The runner:

1. writes ``.context/wiki/.refresh.lock`` with its own PID;
2. calls :func:`libs.copilot.orchestrator.refresh_wiki` synchronously;
3. unlinks the lock on exit (success or failure).

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
import sys
import time
import traceback
from pathlib import Path


def _lock_path(root: Path) -> Path:
    return root / ".context" / "wiki" / ".refresh.lock"


def _write_lock(root: Path, *, all_modules: bool) -> None:
    lock = _lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.time(),
                "all_modules": all_modules,
            }
        ),
        encoding="utf-8",
    )


def _clear_lock(root: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        _lock_path(root).unlink()


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

    _write_lock(root, all_modules=args.all_modules)
    log.info("start root=%s all_modules=%s", root, args.all_modules)
    exit_code = 0
    try:
        # Deferred import: `orchestrator` pulls the full scanning stack.
        # Importing lazily keeps `python -m libs.copilot._wiki_bg_runner --help`
        # cheap and side-effect-free.
        from libs.copilot.orchestrator import refresh_wiki  # noqa: PLC0415

        report = refresh_wiki(root, all_modules=args.all_modules)
        log.info(
            "done updated=%s refreshed=%s messages=%s",
            report.wiki_modules_updated,
            report.wiki_refreshed,
            report.messages,
        )
    except Exception:  # pragma: no cover — surface full trace in the log file
        log.error("wiki refresh crashed:\n%s", traceback.format_exc())
        exit_code = 1
    finally:
        _clear_lock(root)
    return exit_code


if __name__ == "__main__":  # pragma: no cover — entrypoint
    sys.exit(main())
