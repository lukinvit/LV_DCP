"""Debounce buffer for FS events — groups rapid-fire changes into scan batches."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from threading import Lock


class DebounceBuffer:
    """Thread-safe buffer for file-change events awaiting a scan.

    Tracks modified and deleted paths separately so that the daemon can:
    - call ``cache.delete_file`` for deleted paths, and
    - call ``scan_project(..., only=modified)`` for modified/created paths.

    If a file is deleted and then re-created before the buffer is flushed,
    it moves back to *modified* (the creation wins).
    """

    def __init__(self, *, debounce_seconds: float = 2.0) -> None:
        self._debounce_seconds = debounce_seconds
        self._modified: dict[Path, set[str]] = defaultdict(set)
        self._deleted: dict[Path, set[str]] = defaultdict(set)
        self._lock = Lock()

    def add(self, project_root: Path, rel_path: str, event_type: str) -> None:
        with self._lock:
            if event_type == "deleted":
                self._deleted[project_root].add(rel_path)
                # Remove from modified — no point scanning a file that's gone.
                self._modified[project_root].discard(rel_path)
            else:
                self._modified[project_root].add(rel_path)
                # File re-created after deletion — remove from deleted.
                self._deleted[project_root].discard(rel_path)

    def flush_all(self) -> dict[Path, tuple[set[str], set[str]]]:
        """Return pending events and clear the buffer.

        Returns a mapping of ``project_root`` to
        ``(modified_paths, deleted_paths)``.
        """
        with self._lock:
            all_projects = set(self._modified.keys()) | set(self._deleted.keys())
            flushed = {
                p: (
                    set(self._modified.get(p, set())),
                    set(self._deleted.get(p, set())),
                )
                for p in all_projects
            }
            self._modified.clear()
            self._deleted.clear()
            return flushed

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._modified) or bool(self._deleted)

    @property
    def debounce_seconds(self) -> float:
        return self._debounce_seconds
