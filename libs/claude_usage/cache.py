"""Incremental cache for Claude Code session JSONL files.

Stores (session_file_path → (last_byte_offset, list[UsageEvent])) in sqlite.
On sync, checks file st_size vs cached offset, reads only the tail, updates.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from libs.claude_usage.reader import UsageEvent, read_session_file

DEFAULT_CACHE_PATH = Path.home() / ".lvdcp" / "claude_usage.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_cache (
    session_path   TEXT PRIMARY KEY,
    last_offset    INTEGER NOT NULL,
    events_json    TEXT NOT NULL,
    updated_at     REAL NOT NULL
);
"""


class UsageCache:
    def __init__(self, db_path: Path = DEFAULT_CACHE_PATH) -> None:
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

    def sync_and_query(
        self,
        session_file: Path,
        *,
        since_ts: float,
    ) -> list[UsageEvent]:
        """Ensure cache is up to date for *session_file*, then return events >= since_ts."""
        if not session_file.exists():
            return []
        current_size = session_file.stat().st_size
        conn = self._connect()
        row = conn.execute(
            "SELECT last_offset, events_json FROM session_cache WHERE session_path = ?",
            (str(session_file),),
        ).fetchone()

        if row is None:
            cached_events: list[UsageEvent] = []
            last_offset = 0
        else:
            last_offset = int(row[0])
            data = json.loads(row[1])
            cached_events = [UsageEvent(**e) for e in data]

        if current_size > last_offset:
            new_events = list(read_session_file(session_file, start_offset=last_offset))
            cached_events.extend(new_events)
            payload = json.dumps([asdict(e) for e in cached_events])
            conn.execute(
                "INSERT OR REPLACE INTO session_cache "
                "(session_path, last_offset, events_json, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (str(session_file), current_size, payload, time.time()),
            )
            conn.commit()

        return [e for e in cached_events if e.timestamp_unix >= since_ts]
