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
import sqlite3
import sys
import time
import typing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from libs.core.paths import is_ignored, normalize_path
from libs.core.projects_config import ObsidianConfig, WikiConfig, load_config
from libs.project_index.index import ProjectIndex
from libs.scan_history.store import (
    ScanEvent,
    ScanHistoryStore,
    append_event,
    resolve_default_store_path,
)
from libs.scanning.scanner import scan_project
from libs.storage.sqlite_cache import CacheCorruptError
from watchdog.events import FileSystemEvent, PatternMatchingEventHandler
from watchdog.observers import Observer

from apps.agent.config import list_projects, update_last_scan
from apps.agent.handler import DebounceBuffer
from apps.agent.obsidian_worker import run_obsidian_sync
from apps.agent.wiki_worker import run_wiki_update

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "lvdcp-agent"

# Projects that have raised ``CacheCorruptError`` are skipped for the
# remainder of the daemon's lifetime so a single corrupt cache cannot keep
# crashing on every edit-block. Recovery requires the user to delete the
# project's ``.context/`` directory and restart the daemon (which clears
# this set).
_QUARANTINED: dict[Path, str] = {}


def reset_quarantine() -> None:
    """Clear the in-process project quarantine. Test-only entry point."""
    _QUARANTINED.clear()


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


def process_pending_events(  # noqa: PLR0913, PLR0912
    buffer: DebounceBuffer,
    logger: typing.Callable[[str], None] = lambda msg: None,
    *,
    config_path: Path | None = None,
    wiki_pool: ThreadPoolExecutor | None = None,
    wiki_config: WikiConfig | None = None,
    obsidian_pool: ThreadPoolExecutor | None = None,
    obsidian_config: ObsidianConfig | None = None,
) -> dict[Path, int]:
    """Flush buffer and process each project.

    For each project:
    1. Deletes stale cache entries for files reported as deleted.
    2. Runs an incremental scan limited to the modified/created paths.

    If *config_path* is given, updates last_scan_at_iso / last_scan_status in
    that config.yaml after each project's scan pass.

    Returns the reparse count per project.
    """
    pending = buffer.flush_all()
    results: dict[Path, int] = {}
    for project_root, (modified, deleted) in pending.items():
        # Skip projects that already raised ``CacheCorruptError`` this
        # session — the cache won't heal on its own and re-attempting
        # only burns CPU + log noise. See _QUARANTINED comment above.
        if project_root in _QUARANTINED:
            logger(f"[skip] {project_root.name}: quarantined ({_QUARANTINED[project_root]})")
            continue

        scan_status = "ok"
        try:
            if deleted:
                with ProjectIndex.open(project_root) as idx:
                    for rel in deleted:
                        idx.delete_file(rel)
                logger(f"[delete] {project_root.name}: {len(deleted)} removed")

            if modified:
                result = scan_project(project_root, mode="incremental", only=modified)
                results[project_root] = result.files_reparsed
                logger(f"[scan] {project_root.name}: {result.files_reparsed} reparsed")

                # Post-scan wiki hook (best-effort, never blocks daemon)
                if (
                    wiki_pool is not None
                    and wiki_config is not None
                    and result.wiki_dirty_count >= wiki_config.dirty_threshold
                ):
                    wiki_pool.submit(run_wiki_update, project_root, wiki_config)
                    logger(
                        f"[wiki] {project_root.name}: "
                        f"{result.wiki_dirty_count} dirty modules, update queued"
                    )

                # Post-scan Obsidian sync hook — debounced inside the worker
                if obsidian_pool is not None and obsidian_config is not None:
                    obsidian_pool.submit(run_obsidian_sync, project_root, obsidian_config)
            else:
                results[project_root] = 0
        except CacheCorruptError as exc:
            scan_status = "error"
            _QUARANTINED[project_root] = str(exc)
            logger(
                f"[quarantine] {project_root.name}: cache corrupt — will skip "
                f"until daemon restart. Recovery: delete "
                f"{project_root}/.context/ and re-run `ctx scan`. ({exc})"
            )
        except Exception as exc:
            scan_status = "error"
            logger(f"[error] processing failed for {project_root}: {exc}")

        if config_path is not None:
            try:
                ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                update_last_scan(config_path, project_root, status=scan_status, ts_iso=ts)
            except OSError as cfg_exc:
                logger(f"[warn] config.yaml update failed for {project_root}: {cfg_exc}")

        # Append scan_history event (best-effort, never kill daemon)
        try:
            history_store = ScanHistoryStore(resolve_default_store_path())
            history_store.migrate()
            append_event(
                history_store,
                event=ScanEvent(
                    project_root=str(project_root.resolve()),
                    timestamp=time.time(),
                    files_reparsed=results.get(project_root, 0),
                    files_scanned=0,  # daemon only tracks reparsed
                    duration_ms=0.0,  # daemon doesn't time individual projects
                    status=scan_status,
                    source="daemon",
                ),
            )
            history_store.close()
        except (OSError, sqlite3.DatabaseError):
            pass

    return results


def run_daemon(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Main daemon entry point."""
    buffer = DebounceBuffer(debounce_seconds=2.0)
    observer = Observer()
    stop_event = Event()

    cfg = load_config(config_path)
    wiki_pool = ThreadPoolExecutor(max_workers=cfg.wiki.max_workers)
    obsidian_pool = ThreadPoolExecutor(max_workers=1)

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
            process_pending_events(
                buffer,
                logger=print,
                config_path=config_path,
                wiki_pool=wiki_pool if cfg.wiki.auto_update_after_scan else None,
                wiki_config=cfg.wiki if cfg.wiki.auto_update_after_scan else None,
                obsidian_pool=obsidian_pool if cfg.obsidian.auto_sync_after_scan else None,
                obsidian_config=cfg.obsidian if cfg.obsidian.auto_sync_after_scan else None,
            )
    finally:
        observer.stop()
        observer.join()
        wiki_pool.shutdown(wait=False)
        obsidian_pool.shutdown(wait=False)


if __name__ == "__main__":
    run_daemon()
