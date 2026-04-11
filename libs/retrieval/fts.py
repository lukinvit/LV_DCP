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
        and_query, or_query = self._sanitize(query)
        if not and_query and not or_query:
            return []
        # Try strict AND first; fall back to OR if no results
        for fts_query in filter(None, [and_query, or_query]):
            try:
                rows = conn.execute(
                    """
                    SELECT path, -bm25(fts_files) AS score
                    FROM fts_files
                    WHERE fts_files MATCH ?
                    ORDER BY score DESC
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if rows:
                return [(path, float(score)) for path, score in rows]
        return []

    # Common English stopwords that add noise to FTS queries
    _STOPWORDS: frozenset[str] = frozenset(
        {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "shall",
            "can",
            "to",
            "of",
            "in",
            "on",
            "at",
            "by",
            "for",
            "with",
            "from",
            "and",
            "or",
            "but",
            "not",
            "no",
            "nor",
            "so",
            "yet",
            "how",
            "where",
            "which",
            "what",
            "when",
            "who",
            "that",
            "i",
            "it",
            "its",
            "if",
            "as",
            "up",
        }
    )

    @classmethod
    def _sanitize(cls, query: str) -> tuple[str, str]:
        """Return (and_query, or_query) pair.

        ``and_query`` — significant tokens joined with AND (empty string if ≤1 token).
        ``or_query``  — all tokens ≥2 chars joined with OR (always non-empty if query has content).
        Caller should try AND first, fall back to OR if AND returns no results.
        """
        # Strip FTS5 special characters except alphanumerics, underscores, dots, spaces
        allowed = []
        for ch in query:
            if ch.isalnum() or ch in " _.":
                allowed.append(ch)
            else:
                allowed.append(" ")
        cleaned = " ".join("".join(allowed).split())
        if not cleaned:
            return "", ""
        all_tokens = cleaned.split()
        # OR query: all tokens ≥2 chars
        or_tokens = [f'"{t}"*' for t in all_tokens if len(t) >= 2]
        or_query = " OR ".join(or_tokens) if or_tokens else ""
        # AND query: meaningful tokens only (≥3 chars, not stopwords)
        and_tokens = [
            f'"{t}"*' for t in all_tokens if len(t) >= 3 and t.lower() not in cls._STOPWORDS
        ]
        # Only use AND if we have 2+ meaningful tokens (single token AND == OR)
        and_query = " AND ".join(and_tokens) if len(and_tokens) >= 2 else ""
        return and_query, or_query
