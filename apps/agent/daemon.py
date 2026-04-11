"""LV_DCP auto-indexing daemon.

Long-running process that:
- Reads ~/.lvdcp/config.yaml to know which projects to watch
- Schedules a watchdog Observer (FSEventsObserver on macOS) per project
- Collects file events into a debounce buffer
- Every N seconds, flushes the buffer and runs incremental scans

Handles SIGTERM/SIGINT gracefully. Logs to ~/Library/Logs/lvdcp-agent/.
"""

from __future__ import annotations

import signal
import sys
import time
import typing
from pathlib import Path
from threading import Event

from libs.core.paths import is_ignored, normalize_path
from libs.scanning.scanner import scan_project
from watchdog.events import FileSystemEvent, PatternMatchingEventHandler
from watchdog.observers import Observer

from apps.agent.config import list_projects
from apps.agent.handler import DebounceBuffer

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "lvdcp-agent"

PATTERNS = [
    "*.py",
    "*.md",
    "*.markdown",
    "*.yaml",
    "*.yml",
    "*.json",
    "*.toml",
]


class DaemonEventHandler(PatternMatchingEventHandler):
    def __init__(self, project_root: Path, buffer: DebounceBuffer) -> None:
        super().__init__(
            patterns=PATTERNS,
            ignore_directories=True,
        )
        self._project_root = project_root
        self._buffer = buffer

    def on_any_event(self, event: FileSystemEvent) -> None:
        abs_path = Path(event.src_path)
        try:
            rel = normalize_path(abs_path, root=self._project_root)
        except ValueError:
            return
        if is_ignored(rel):
            return
        self._buffer.add(self._project_root, rel, event.event_type)


def process_pending_events(
    buffer: DebounceBuffer,
    logger: typing.Callable[[str], None] = lambda msg: None,
) -> dict[Path, int]:
    """Flush buffer and scan each project once. Returns reparse count per project."""
    pending = buffer.flush_all()
    results: dict[Path, int] = {}
    for project_root, changed_paths in pending.items():
        try:
            result = scan_project(project_root, mode="incremental", only=changed_paths)
            results[project_root] = result.files_reparsed
            logger(f"[scan] {project_root.name}: {result.files_reparsed} reparsed")
        except Exception as exc:
            logger(f"[error] scan failed for {project_root}: {exc}")
    return results


def run_daemon(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    foreground: bool = True,
) -> None:
    """Main daemon entry point."""
    buffer = DebounceBuffer(debounce_seconds=2.0)
    observer = Observer()
    stop_event = Event()

    def handle_signal(signum: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    projects = list_projects(config_path)
    for entry in projects:
        root = entry.root
        if not root.exists():
            print(f"[warn] project does not exist: {root}", file=sys.stderr)
            continue
        handler = DaemonEventHandler(root, buffer)
        observer.schedule(handler, str(root), recursive=True)
        print(f"[info] watching {root}")

    if not projects:
        print("[warn] no projects registered; daemon will idle")

    observer.start()

    try:
        while not stop_event.is_set():
            time.sleep(buffer.debounce_seconds)
            process_pending_events(buffer, logger=print)
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    run_daemon(foreground=True)
