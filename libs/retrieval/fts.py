"""SQLite FTS5 wrapper for full-text search over file contents and symbol text.

Two-layer schema:
- fts_files(path, content, content_stemmed) — one row per file
- external delete/replace handled via explicit DELETE + INSERT
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from libs.retrieval._stopwords import STOPWORDS
from libs.retrieval.identifiers import expand_query_terms, path_alias_text
from libs.retrieval.stemmer import normalize_query, normalize_text
from libs.retrieval.term_dict import expand_query


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
        try:
            conn.execute("SELECT content_stemmed FROM fts_files LIMIT 0")
        except sqlite3.OperationalError:
            conn.execute("DROP TABLE IF EXISTS fts_files")
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(
                path UNINDEXED,
                content,
                content_stemmed,
                tokenize = 'porter unicode61'
            );
            """
        )
        conn.commit()

    def index_file(self, path: str, content: str) -> None:
        conn = self._connect()
        augmented = f"{path}\n{path_alias_text(path)}\n{content}"
        stemmed = normalize_text(augmented)
        conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
        conn.execute(
            "INSERT INTO fts_files (path, content, content_stemmed) VALUES (?, ?, ?)",
            (path, augmented, stemmed),
        )
        conn.commit()

    def delete_file(self, path: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def search(self, query: str, *, limit: int = 20) -> list[tuple[str, float]]:
        query = expand_query(query)
        conn = self._connect()
        query_variants = [
            expand_query_terms(normalize_query(query)),
            expand_query_terms(query),
        ]
        for terms in query_variants:
            and_query, or_query = self._sanitize_terms(terms)
            if not and_query and not or_query:
                continue
            # Try strict AND first; fall back to OR if no results
            for fts_query in filter(None, [and_query, or_query]):
                fts_expr = f"{{content content_stemmed}}: ({fts_query})"
                try:
                    rows = conn.execute(
                        """
                        SELECT path, -bm25(fts_files) AS score
                        FROM fts_files
                        WHERE fts_files MATCH ?
                        ORDER BY score DESC
                        LIMIT ?
                        """,
                        (fts_expr, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                if rows:
                    return [(path, float(score)) for path, score in rows]
        return []

    # Shared stopwords (see libs/retrieval/_stopwords.py)
    _STOPWORDS: frozenset[str] = STOPWORDS

    @classmethod
    def _sanitize_terms(cls, terms: list[str]) -> tuple[str, str]:
        """Return (and_query, or_query) pair from already tokenized query terms.

        ``and_query`` — significant tokens joined with AND (empty string if ≤1 token).
        ``or_query``  — all tokens ≥2 chars joined with OR (always non-empty if query has content).
        Caller should try AND first, fall back to OR if AND returns no results.
        """
        cleaned_terms = [term for term in terms if term]
        if not cleaned_terms:
            return "", ""
        # OR query: all tokens ≥2 chars
        or_tokens = [f'"{t}"*' for t in cleaned_terms if len(t) >= 2]
        or_query = " OR ".join(or_tokens) if or_tokens else ""
        # AND query: meaningful tokens only (≥3 chars, not stopwords)
        and_tokens = [
            f'"{t}"*' for t in cleaned_terms if len(t) >= 3 and t.lower() not in cls._STOPWORDS
        ]
        # Only use AND if we have 2+ meaningful tokens (single token AND == OR)
        and_query = " AND ".join(and_tokens) if len(and_tokens) >= 2 else ""
        return and_query, or_query
