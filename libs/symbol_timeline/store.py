"""Symbol timeline event store — append-only SQLite at ``~/.lvdcp/symbol_timeline.db``.

Mirrors :mod:`libs.scan_history.store` in shape: WAL mode, lazy connect,
env-overridable path, retention prune on every append. Four tables:

* ``symbol_timeline_events`` — added / modified / removed / renamed / moved
* ``symbol_timeline_snapshots`` — per-release immutable anchors
* ``symbol_timeline_rename_edges`` — pair links when rename detected
* ``symbol_timeline_scan_state`` — per-project last-scan metadata

Spec: specs/010-feature-timeline-index/data-model.md §1.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_STORE_PATH: Final[Path] = Path.home() / ".lvdcp" / "symbol_timeline.db"

_VALID_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {"added", "modified", "removed", "renamed", "moved"}
)


@dataclass(frozen=True)
class TimelineEvent:
    """One event in the life of a symbol — see spec §Key Entities."""

    project_root: str
    symbol_id: str
    event_type: str  # one of _VALID_EVENT_TYPES
    commit_sha: str | None
    timestamp: float
    author: str | None
    content_hash: str | None
    file_path: str
    qualified_name: str | None = None
    extra_json: str | None = None
    orphaned: bool = False


@dataclass(frozen=True)
class SnapshotRow:
    """Row in ``symbol_timeline_snapshots`` (FR-005)."""

    snapshot_id: str
    project_root: str
    tag: str
    head_sha: str
    timestamp: float
    symbol_count: int
    checksum: str
    tag_invalidated: bool = False
    ref_kind: str = "git_tag"


@dataclass(frozen=True)
class RenameEdgeRow:
    """Row in ``symbol_timeline_rename_edges`` (FR-007)."""

    project_root: str
    old_symbol_id: str
    new_symbol_id: str
    commit_sha: str | None
    timestamp: float
    confidence: float
    is_candidate: bool = False


@dataclass(frozen=True)
class ScanState:
    """Per-project last-scan metadata — drives diff + reconcile."""

    project_root: str
    last_scan_commit_sha: str | None
    last_scan_ts: float


_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS symbol_timeline_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root   TEXT    NOT NULL,
    symbol_id      TEXT    NOT NULL,
    event_type     TEXT    NOT NULL CHECK (event_type IN
                    ('added','modified','removed','renamed','moved')),
    commit_sha     TEXT,
    timestamp      REAL    NOT NULL,
    author         TEXT,
    content_hash   TEXT,
    file_path      TEXT    NOT NULL,
    qualified_name TEXT,
    extra_json     TEXT,
    orphaned       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tle_root_symbol_ts
    ON symbol_timeline_events (project_root, symbol_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tle_root_commit
    ON symbol_timeline_events (project_root, commit_sha);
CREATE INDEX IF NOT EXISTS idx_tle_root_ts
    ON symbol_timeline_events (project_root, timestamp);
CREATE INDEX IF NOT EXISTS idx_tle_root_type_ts
    ON symbol_timeline_events (project_root, event_type, timestamp);

CREATE TABLE IF NOT EXISTS symbol_timeline_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root    TEXT    NOT NULL,
    snapshot_id     TEXT    NOT NULL UNIQUE,
    tag             TEXT    NOT NULL,
    head_sha        TEXT    NOT NULL,
    timestamp       REAL    NOT NULL,
    symbol_count    INTEGER NOT NULL,
    checksum        TEXT    NOT NULL,
    tag_invalidated INTEGER NOT NULL DEFAULT 0,
    ref_kind        TEXT    NOT NULL DEFAULT 'git_tag'
);
CREATE INDEX IF NOT EXISTS idx_tls_root_ts
    ON symbol_timeline_snapshots (project_root, timestamp);
CREATE INDEX IF NOT EXISTS idx_tls_root_tag
    ON symbol_timeline_snapshots (project_root, tag);

CREATE TABLE IF NOT EXISTS symbol_timeline_rename_edges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root     TEXT    NOT NULL,
    old_symbol_id    TEXT    NOT NULL,
    new_symbol_id    TEXT    NOT NULL,
    commit_sha       TEXT,
    timestamp        REAL    NOT NULL,
    confidence       REAL    NOT NULL,
    is_candidate     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tre_root_old
    ON symbol_timeline_rename_edges (project_root, old_symbol_id);
CREATE INDEX IF NOT EXISTS idx_tre_root_new
    ON symbol_timeline_rename_edges (project_root, new_symbol_id);

CREATE TABLE IF NOT EXISTS symbol_timeline_scan_state (
    project_root         TEXT PRIMARY KEY,
    last_scan_commit_sha TEXT,
    last_scan_ts         REAL NOT NULL
);
"""


class SymbolTimelineStore:
    """Lazy-connect SQLite wrapper. Mirrors :class:`libs.scan_history.store.ScanHistoryStore`."""

    def __init__(self, db_path: Path = DEFAULT_STORE_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def migrate(self) -> None:
        conn = self._connect()
        conn.executescript(_SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def append_event(
    store: SymbolTimelineStore,
    *,
    event: TimelineEvent,
    retention_days: int | None = None,
) -> None:
    """Insert one event and (optionally) prune rows older than retention window.

    ``retention_days=None`` keeps everything (spec FR-009 default).
    """
    if event.event_type not in _VALID_EVENT_TYPES:
        msg = f"invalid event_type: {event.event_type!r}"
        raise ValueError(msg)

    conn = store._connect()
    conn.execute(
        "INSERT INTO symbol_timeline_events ("
        "project_root, symbol_id, event_type, commit_sha, timestamp, "
        "author, content_hash, file_path, qualified_name, extra_json, orphaned"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.project_root,
            event.symbol_id,
            event.event_type,
            event.commit_sha,
            event.timestamp,
            event.author,
            event.content_hash,
            event.file_path,
            event.qualified_name,
            event.extra_json,
            1 if event.orphaned else 0,
        ),
    )
    if retention_days is not None and retention_days > 0:
        cutoff = time.time() - retention_days * 86400
        conn.execute("DELETE FROM symbol_timeline_events WHERE timestamp < ?", (cutoff,))
    conn.commit()


def events_for_symbol(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    symbol_id: str,
    include_orphaned: bool = False,
) -> list[TimelineEvent]:
    """Return full event history of one symbol, oldest first."""
    conn = store._connect()
    query = (
        "SELECT project_root, symbol_id, event_type, commit_sha, timestamp, "
        "author, content_hash, file_path, qualified_name, extra_json, orphaned "
        "FROM symbol_timeline_events "
        "WHERE project_root = ? AND symbol_id = ? "
    )
    params: list[object] = [project_root, symbol_id]
    if not include_orphaned:
        query += "AND orphaned = 0 "
    query += "ORDER BY timestamp ASC, id ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_event(r) for r in rows]


def events_between(  # noqa: PLR0913 - keyword-only query API
    store: SymbolTimelineStore,
    *,
    project_root: str,
    from_ts: float,
    to_ts: float,
    event_types: list[str] | None = None,
    include_orphaned: bool = False,
) -> list[TimelineEvent]:
    """Return all events in ``[from_ts, to_ts]`` (inclusive), oldest first.

    ``event_types=None`` returns all kinds; pass a list to filter.
    """
    conn = store._connect()
    query = (
        "SELECT project_root, symbol_id, event_type, commit_sha, timestamp, "
        "author, content_hash, file_path, qualified_name, extra_json, orphaned "
        "FROM symbol_timeline_events "
        "WHERE project_root = ? AND timestamp >= ? AND timestamp <= ? "
    )
    params: list[object] = [project_root, from_ts, to_ts]
    if event_types:
        placeholders = ",".join("?" for _ in event_types)
        query += f"AND event_type IN ({placeholders}) "
        params.extend(event_types)
    if not include_orphaned:
        query += "AND orphaned = 0 "
    query += "ORDER BY timestamp ASC, id ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_event(r) for r in rows]


def insert_snapshot(store: SymbolTimelineStore, *, snapshot: SnapshotRow) -> None:
    """Insert an immutable release snapshot (FR-005). Idempotent by ``snapshot_id``."""
    conn = store._connect()
    conn.execute(
        "INSERT OR IGNORE INTO symbol_timeline_snapshots ("
        "project_root, snapshot_id, tag, head_sha, timestamp, symbol_count, "
        "checksum, tag_invalidated, ref_kind"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot.project_root,
            snapshot.snapshot_id,
            snapshot.tag,
            snapshot.head_sha,
            snapshot.timestamp,
            snapshot.symbol_count,
            snapshot.checksum,
            1 if snapshot.tag_invalidated else 0,
            snapshot.ref_kind,
        ),
    )
    conn.commit()


def latest_snapshot(
    store: SymbolTimelineStore, *, project_root: str, tag: str
) -> SnapshotRow | None:
    """Return the newest snapshot for (project_root, tag), or None if none."""
    conn = store._connect()
    row = conn.execute(
        "SELECT project_root, snapshot_id, tag, head_sha, timestamp, "
        "symbol_count, checksum, tag_invalidated, ref_kind "
        "FROM symbol_timeline_snapshots "
        "WHERE project_root = ? AND tag = ? "
        "ORDER BY timestamp DESC, id DESC LIMIT 1",
        (project_root, tag),
    ).fetchone()
    if row is None:
        return None
    return SnapshotRow(
        project_root=row[0],
        snapshot_id=row[1],
        tag=row[2],
        head_sha=row[3],
        timestamp=row[4],
        symbol_count=row[5],
        checksum=row[6],
        tag_invalidated=bool(row[7]),
        ref_kind=row[8],
    )


def append_rename_edge(store: SymbolTimelineStore, *, edge: RenameEdgeRow) -> None:
    """Insert one rename edge. Not idempotent — caller deduplicates if needed."""
    conn = store._connect()
    conn.execute(
        "INSERT INTO symbol_timeline_rename_edges ("
        "project_root, old_symbol_id, new_symbol_id, commit_sha, timestamp, "
        "confidence, is_candidate"
        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            edge.project_root,
            edge.old_symbol_id,
            edge.new_symbol_id,
            edge.commit_sha,
            edge.timestamp,
            edge.confidence,
            1 if edge.is_candidate else 0,
        ),
    )
    conn.commit()


def upsert_scan_state(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    last_scan_commit_sha: str | None,
    last_scan_ts: float,
) -> None:
    """Record the commit_sha and timestamp of the most recent scan for ``project_root``."""
    conn = store._connect()
    conn.execute(
        "INSERT INTO symbol_timeline_scan_state "
        "(project_root, last_scan_commit_sha, last_scan_ts) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(project_root) DO UPDATE SET "
        "last_scan_commit_sha = excluded.last_scan_commit_sha, "
        "last_scan_ts = excluded.last_scan_ts",
        (project_root, last_scan_commit_sha, last_scan_ts),
    )
    conn.commit()


def get_scan_state(store: SymbolTimelineStore, *, project_root: str) -> ScanState | None:
    """Return the most recent scan metadata for ``project_root`` or ``None``."""
    conn = store._connect()
    row = conn.execute(
        "SELECT project_root, last_scan_commit_sha, last_scan_ts "
        "FROM symbol_timeline_scan_state "
        "WHERE project_root = ?",
        (project_root,),
    ).fetchone()
    if row is None:
        return None
    return ScanState(project_root=row[0], last_scan_commit_sha=row[1], last_scan_ts=row[2])


def reconcile_orphaned_events(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    known_commit_shas: set[str],
) -> int:
    """Mark events whose ``commit_sha`` is no longer reachable as ``orphaned``.

    Called after a commit rewrite (rebase, amend) to prevent the timeline from
    showing history for commits that no longer exist. Events with ``commit_sha
    IS NULL`` are never orphaned (they record non-git-attributed changes).

    Returns the number of rows newly flagged.
    """
    conn = store._connect()
    # Gather distinct commit_shas for this project that are not NULL and not orphaned.
    current_rows = conn.execute(
        "SELECT DISTINCT commit_sha FROM symbol_timeline_events "
        "WHERE project_root = ? AND commit_sha IS NOT NULL AND orphaned = 0",
        (project_root,),
    ).fetchall()
    stale = [r[0] for r in current_rows if r[0] not in known_commit_shas]
    if not stale:
        return 0
    placeholders = ",".join("?" for _ in stale)
    cur = conn.execute(
        # ruff: noqa: S608 - placeholders is a fixed string of '?' per value
        f"UPDATE symbol_timeline_events SET orphaned = 1 "
        f"WHERE project_root = ? AND commit_sha IN ({placeholders})",
        (project_root, *stale),
    )
    conn.commit()
    return cur.rowcount or 0


def resolve_default_store_path() -> Path:
    """Env-overridable store path (``LVDCP_TIMELINE_DB``) for test isolation."""
    override = os.environ.get("LVDCP_TIMELINE_DB")
    if override:
        return Path(override)
    return DEFAULT_STORE_PATH


def _row_to_event(row: tuple) -> TimelineEvent:  # type: ignore[type-arg]
    return TimelineEvent(
        project_root=row[0],
        symbol_id=row[1],
        event_type=row[2],
        commit_sha=row[3],
        timestamp=row[4],
        author=row[5],
        content_hash=row[6],
        file_path=row[7],
        qualified_name=row[8],
        extra_json=row[9],
        orphaned=bool(row[10]),
    )
