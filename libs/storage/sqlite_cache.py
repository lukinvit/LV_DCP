"""SQLite local cache for file state, symbols, and relations.

Single-writer (the CLI process). Schema is versioned via PRAGMA user_version.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path

from libs.core.entities import File, Relation, RelationType, Symbol, SymbolType

# Phase 1 has no formal migration path; bumping this constant is advisory.
# ADR-002 Phase 2 will introduce proper migration dispatch (see review issue I2).
SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path          TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    language      TEXT NOT NULL,
    role          TEXT NOT NULL,
    is_generated  INTEGER NOT NULL DEFAULT 0,
    is_binary     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS symbols (
    fq_name         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    symbol_type     TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    parent_fq_name  TEXT,
    signature       TEXT,
    docstring       TEXT,
    FOREIGN KEY (file_path) REFERENCES files(path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

CREATE TABLE IF NOT EXISTS relations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    src_type       TEXT NOT NULL,
    src_ref        TEXT NOT NULL,
    dst_type       TEXT NOT NULL,
    dst_ref        TEXT NOT NULL,
    relation_type  TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 1.0,
    provenance     TEXT NOT NULL DEFAULT 'deterministic',
    origin_file    TEXT NOT NULL,
    FOREIGN KEY (origin_file) REFERENCES files(path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rel_origin ON relations(origin_file);
CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src_ref);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst_ref);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relations(relation_type);
"""


class SqliteCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def migrate(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    # --- files --------------------------------------------------------------

    def put_file(self, file: File) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO files (path, content_hash, size_bytes, language, role, is_generated, is_binary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                content_hash = excluded.content_hash,
                size_bytes = excluded.size_bytes,
                language = excluded.language,
                role = excluded.role,
                is_generated = excluded.is_generated,
                is_binary = excluded.is_binary
            """,
            (
                file.path,
                file.content_hash,
                file.size_bytes,
                file.language,
                file.role,
                int(file.is_generated),
                int(file.is_binary),
            ),
        )
        conn.commit()

    def get_file(self, path: str) -> File | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT path, content_hash, size_bytes, language, role, is_generated, is_binary "
            "FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        if row is None:
            return None
        return File(
            path=row[0],
            content_hash=row[1],
            size_bytes=row[2],
            language=row[3],
            role=row[4],
            is_generated=bool(row[5]),
            is_binary=bool(row[6]),
        )

    def delete_file(self, path: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
        conn.commit()

    def file_count(self) -> int:
        conn = self._connect()
        return int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def iter_files(self) -> Iterator[File]:
        conn = self._connect()
        for row in conn.execute(
            "SELECT path, content_hash, size_bytes, language, role, is_generated, is_binary FROM files"
        ):
            yield File(
                path=row[0],
                content_hash=row[1],
                size_bytes=row[2],
                language=row[3],
                role=row[4],
                is_generated=bool(row[5]),
                is_binary=bool(row[6]),
            )

    # --- symbols ------------------------------------------------------------

    def replace_symbols(self, *, file_path: str, symbols: Iterable[Symbol]) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
        conn.executemany(
            """
            INSERT OR REPLACE INTO symbols
                (fq_name, name, symbol_type, file_path, start_line, end_line,
                 parent_fq_name, signature, docstring)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    s.fq_name,
                    s.name,
                    s.symbol_type.value,
                    s.file_path,
                    s.start_line,
                    s.end_line,
                    s.parent_fq_name,
                    s.signature,
                    s.docstring,
                )
                for s in symbols
            ],
        )
        conn.commit()

    def iter_symbols(self) -> Iterator[Symbol]:
        conn = self._connect()
        for row in conn.execute(
            "SELECT name, fq_name, symbol_type, file_path, start_line, end_line, "
            "parent_fq_name, signature, docstring FROM symbols"
        ):
            yield Symbol(
                name=row[0],
                fq_name=row[1],
                symbol_type=SymbolType(row[2]),
                file_path=row[3],
                start_line=row[4],
                end_line=row[5],
                parent_fq_name=row[6],
                signature=row[7],
                docstring=row[8],
            )

    # --- relations ----------------------------------------------------------

    def replace_relations(self, *, file_path: str, relations: Iterable[Relation]) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM relations WHERE origin_file = ?", (file_path,))
        conn.executemany(
            """
            INSERT INTO relations
                (src_type, src_ref, dst_type, dst_ref, relation_type, confidence, provenance, origin_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.src_type,
                    r.src_ref,
                    r.dst_type,
                    r.dst_ref,
                    r.relation_type.value,
                    r.confidence,
                    r.provenance,
                    file_path,
                )
                for r in relations
            ],
        )
        conn.commit()

    def iter_relations(self) -> Iterator[Relation]:
        conn = self._connect()
        for row in conn.execute(
            "SELECT src_type, src_ref, dst_type, dst_ref, relation_type, confidence, provenance FROM relations"
        ):
            yield Relation(
                src_type=row[0],
                src_ref=row[1],
                dst_type=row[2],
                dst_ref=row[3],
                relation_type=RelationType(row[4]),
                confidence=row[5],
                provenance=row[6],
            )
