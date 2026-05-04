"""SQLite store for breadcrumb events. Mirrors libs/scan_history layout."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_STORE_PATH = Path.home() / ".lvdcp" / "breadcrumbs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS breadcrumbs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root      TEXT    NOT NULL,
    timestamp         REAL    NOT NULL,
    source            TEXT    NOT NULL,
    cc_session_id     TEXT,
    os_user           TEXT    NOT NULL,
    cc_account_email  TEXT,
    query             TEXT,
    mode              TEXT,
    paths_touched     TEXT,
    todo_snapshot     TEXT,
    turn_summary      TEXT,
    privacy_mode      TEXT    NOT NULL DEFAULT 'local_only'
);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_root_ts
    ON breadcrumbs (project_root, timestamp);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_user_root_ts
    ON breadcrumbs (os_user, project_root, timestamp);
CREATE INDEX IF NOT EXISTS ix_breadcrumbs_session
    ON breadcrumbs (cc_session_id);
"""


class BreadcrumbStore:
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
