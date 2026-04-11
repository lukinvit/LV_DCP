"""Debounce buffer for FS events — groups rapid-fire changes into scan batches."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from threading import Lock


class DebounceBuffer:
    """Thread-safe buffer for file-change events awaiting a scan."""

    def __init__(self, *, debounce_seconds: float = 2.0) -> None:
        self._debounce_seconds = debounce_seconds
        self._by_project: dict[Path, set[str]] = defaultdict(set)
        self._lock = Lock()

    def add(self, project_root: Path, rel_path: str, event_type: str) -> None:
        with self._lock:
            self._by_project[project_root].add(rel_path)

    def flush_all(self) -> dict[Path, set[str]]:
        """Return pending events and clear the buffer."""
        with self._lock:
            flushed = {k: set(v) for k, v in self._by_project.items()}
            self._by_project.clear()
            return flushed

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._by_project)

    @property
    def debounce_seconds(self) -> float:
        return self._debounce_seconds
