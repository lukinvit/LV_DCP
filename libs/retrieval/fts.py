"""SQLite FTS5 wrapper for full-text search over file contents and symbol text.

Two-layer schema:
- fts_files(path, content) — one row per file
- external delete/replace handled via explicit DELETE + INSERT
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class FtsIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def create(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(
                path UNINDEXED,
                content,
                tokenize = 'porter unicode61'
            );
            """
        )
        conn.commit()

    def index_file(self, path: str, content: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
        conn.execute(
            "INSERT INTO fts_files (path, content) VALUES (?, ?)",
            (path, content),
        )
        conn.commit()

    def delete_file(self, path: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
        conn.commit()

    def search(self, query: str, *, limit: int = 20) -> list[tuple[str, float]]:
        conn = self._connect()
        safe_query = self._sanitize(query)
        if not safe_query:
            return []
        rows = conn.execute(
            """
            SELECT path, -bm25(fts_files) AS score
            FROM fts_files
            WHERE fts_files MATCH ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
        return [(path, float(score)) for path, score in rows]

    @staticmethod
    def _sanitize(query: str) -> str:
        # Strip FTS5 special characters except alphanumerics, underscores, dots, spaces
        allowed = []
        for ch in query:
            if ch.isalnum() or ch in " _.":
                allowed.append(ch)
            else:
                allowed.append(" ")
        cleaned = " ".join("".join(allowed).split())
        if not cleaned:
            return ""
        # Wrap each token as prefix search for lenient matching
        tokens = [f'"{t}"*' for t in cleaned.split() if len(t) >= 2]
        return " OR ".join(tokens)
