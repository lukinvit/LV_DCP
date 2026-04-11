"""Scan history store — append-only event log at ~/.lvdcp/scan_history.db.

Retention: rolling 90 days, pruned on every append.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STORE_PATH = Path.home() / ".lvdcp" / "scan_history.db"
RETENTION_SECONDS = 90 * 24 * 3600


@dataclass(frozen=True)
class ScanEvent:
    project_root: str
    timestamp: float
    files_reparsed: int
    files_scanned: int
    duration_ms: float
    status: str  # "ok" | "error"
    source: str  # "daemon" | "manual"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root   TEXT NOT NULL,
    timestamp      REAL NOT NULL,
    files_reparsed INTEGER NOT NULL,
    files_scanned  INTEGER NOT NULL,
    duration_ms    REAL NOT NULL,
    status         TEXT NOT NULL,
    source         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scan_events_root_ts
    ON scan_events (project_root, timestamp);
"""


class ScanHistoryStore:
    def __init__(self, db_path: Path = DEFAULT_STORE_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def migrate(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def append_event(store: ScanHistoryStore, *, event: ScanEvent) -> None:
    """Insert a new scan event and prune anything older than retention window.

    Retention cutoff is anchored on wall-clock `time.time()` so late-arriving
    historical events don't wrongly purge themselves.
    """
    conn = store._connect()
    conn.execute(
        "INSERT INTO scan_events "
        "(project_root, timestamp, files_reparsed, files_scanned, duration_ms, status, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event.project_root,
            event.timestamp,
            event.files_reparsed,
            event.files_scanned,
            event.duration_ms,
            event.status,
            event.source,
        ),
    )
    cutoff = time.time() - RETENTION_SECONDS
    conn.execute("DELETE FROM scan_events WHERE timestamp < ?", (cutoff,))
    conn.commit()


def events_since(
    store: ScanHistoryStore,
    *,
    project_root: str,
    since_ts: float,
) -> list[ScanEvent]:
    """Return scan events for *project_root* with timestamp >= since_ts, ascending."""
    conn = store._connect()
    rows = conn.execute(
        "SELECT project_root, timestamp, files_reparsed, files_scanned, "
        "duration_ms, status, source "
        "FROM scan_events "
        "WHERE project_root = ? AND timestamp >= ? "
        "ORDER BY timestamp ASC",
        (project_root, since_ts),
    ).fetchall()
    return [
        ScanEvent(
            project_root=r[0],
            timestamp=r[1],
            files_reparsed=r[2],
            files_scanned=r[3],
            duration_ms=r[4],
            status=r[5],
            source=r[6],
        )
        for r in rows
    ]


def resolve_default_store_path() -> Path:
    """Return env-overridable default store path (for test isolation)."""
    override = os.environ.get("LVDCP_SCAN_HISTORY_DB")
    if override:
        return Path(override)
    return DEFAULT_STORE_PATH
