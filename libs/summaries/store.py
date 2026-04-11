"""Persistent summary cache at ~/.lvdcp/summaries.db.

Keyed on (content_hash, prompt_version, model_name). The same file processed
by two different models yields two rows. No retention — summaries live forever
because the cache key invalidates automatically on content or prompt change.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STORE_PATH = Path.home() / ".lvdcp" / "summaries.db"


@dataclass(frozen=True)
class SummaryRow:
    content_hash: str
    prompt_version: str
    model_name: str
    project_root: str
    file_path: str
    summary_text: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    created_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    content_hash    TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    project_root    TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    summary_text    TEXT NOT NULL,
    cost_usd        REAL NOT NULL,
    tokens_in       INTEGER NOT NULL,
    tokens_out      INTEGER NOT NULL,
    tokens_cached   INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    PRIMARY KEY (content_hash, prompt_version, model_name)
);
CREATE INDEX IF NOT EXISTS idx_summaries_project_file
    ON summaries (project_root, file_path);
CREATE INDEX IF NOT EXISTS idx_summaries_created_at
    ON summaries (created_at);
"""


class SummaryStore:
    def __init__(self, db_path: Path = DEFAULT_STORE_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def __enter__(self) -> SummaryStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def migrate(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def persist(self, row: SummaryRow) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO summaries "
            "(content_hash, prompt_version, model_name, project_root, file_path, "
            " summary_text, cost_usd, tokens_in, tokens_out, tokens_cached, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.content_hash,
                row.prompt_version,
                row.model_name,
                row.project_root,
                row.file_path,
                row.summary_text,
                row.cost_usd,
                row.tokens_in,
                row.tokens_out,
                row.tokens_cached,
                row.created_at,
            ),
        )
        conn.commit()

    def lookup(
        self,
        *,
        content_hash: str,
        prompt_version: str,
        model_name: str,
    ) -> SummaryRow | None:
        conn = self._connect()
        cur = conn.execute(
            "SELECT content_hash, prompt_version, model_name, project_root, "
            "file_path, summary_text, cost_usd, tokens_in, tokens_out, "
            "tokens_cached, created_at "
            "FROM summaries WHERE content_hash = ? AND prompt_version = ? AND model_name = ?",
            (content_hash, prompt_version, model_name),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SummaryRow(
            content_hash=row[0],
            prompt_version=row[1],
            model_name=row[2],
            project_root=row[3],
            file_path=row[4],
            summary_text=row[5],
            cost_usd=row[6],
            tokens_in=row[7],
            tokens_out=row[8],
            tokens_cached=row[9],
            created_at=row[10],
        )

    def list_for_project(self, project_root: str) -> list[SummaryRow]:
        conn = self._connect()
        cur = conn.execute(
            "SELECT content_hash, prompt_version, model_name, project_root, "
            "file_path, summary_text, cost_usd, tokens_in, tokens_out, "
            "tokens_cached, created_at "
            "FROM summaries WHERE project_root = ? ORDER BY file_path",
            (project_root,),
        )
        return [
            SummaryRow(
                content_hash=r[0], prompt_version=r[1], model_name=r[2],
                project_root=r[3], file_path=r[4], summary_text=r[5],
                cost_usd=r[6], tokens_in=r[7], tokens_out=r[8],
                tokens_cached=r[9], created_at=r[10],
            )
            for r in cur.fetchall()
        ]

    def total_cost_since(self, *, since_ts: float) -> float:
        conn = self._connect()
        cur = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM summaries WHERE created_at >= ?",
            (since_ts,),
        )
        return float(cur.fetchone()[0])


def resolve_default_store_path() -> Path:
    override = os.environ.get("LVDCP_SUMMARIES_DB")
    if override:
        return Path(override)
    return DEFAULT_STORE_PATH
