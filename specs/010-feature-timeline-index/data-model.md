# Data Model: Symbol Timeline Index (Phase 1)

**Date**: 2026-04-22
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

Финальные контракты — SQLite DDL, Python dataclasses, `TimelineSink` Protocol. Любые изменения после этого — через миграцию.

## 1. SQLite schema — `~/.lvdcp/symbol_timeline.db`

```sql
-- Append-only events table (FR-001)
CREATE TABLE IF NOT EXISTS symbol_timeline_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root     TEXT    NOT NULL,
    symbol_id        TEXT    NOT NULL,
    event_type       TEXT    NOT NULL CHECK (event_type IN
                              ('added','modified','removed','renamed','moved')),
    commit_sha       TEXT,
    timestamp        REAL    NOT NULL,
    author           TEXT,              -- email, maskable per privacy_mode
    content_hash     TEXT,
    file_path        TEXT    NOT NULL,
    qualified_name   TEXT,              -- dotted path, used by rename_detect
    extra_json       TEXT,              -- JSON blob for event-specific fields
    orphaned         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tle_root_symbol_ts
    ON symbol_timeline_events (project_root, symbol_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tle_root_commit
    ON symbol_timeline_events (project_root, commit_sha);
CREATE INDEX IF NOT EXISTS idx_tle_root_ts
    ON symbol_timeline_events (project_root, timestamp);
CREATE INDEX IF NOT EXISTS idx_tle_root_type_ts
    ON symbol_timeline_events (project_root, event_type, timestamp);

-- Release snapshots (FR-005)
CREATE TABLE IF NOT EXISTS symbol_timeline_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root       TEXT    NOT NULL,
    snapshot_id        TEXT    NOT NULL UNIQUE,  -- sha256(project_root|tag|head_sha)[:32]
    tag                TEXT    NOT NULL,
    head_sha           TEXT    NOT NULL,
    timestamp          REAL    NOT NULL,
    symbol_count       INTEGER NOT NULL,
    checksum           TEXT    NOT NULL,         -- content anchor, sha256 over sorted symbol_ids
    tag_invalidated    INTEGER NOT NULL DEFAULT 0,
    ref_kind           TEXT    NOT NULL DEFAULT 'git_tag'  -- git_tag | shadow_checkpoint
);
CREATE INDEX IF NOT EXISTS idx_tls_root_ts
    ON symbol_timeline_snapshots (project_root, timestamp);
CREATE INDEX IF NOT EXISTS idx_tls_root_tag
    ON symbol_timeline_snapshots (project_root, tag);

-- Rename edges (FR-007 + R1 hybrid decision)
CREATE TABLE IF NOT EXISTS symbol_timeline_rename_edges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root     TEXT    NOT NULL,
    old_symbol_id    TEXT    NOT NULL,
    new_symbol_id    TEXT    NOT NULL,
    commit_sha       TEXT,
    timestamp        REAL    NOT NULL,
    confidence       REAL    NOT NULL,          -- 0.0..1.0
    is_candidate     INTEGER NOT NULL DEFAULT 0 -- 1 when low-confidence (keep original events too)
);
CREATE INDEX IF NOT EXISTS idx_tre_root_old
    ON symbol_timeline_rename_edges (project_root, old_symbol_id);
CREATE INDEX IF NOT EXISTS idx_tre_root_new
    ON symbol_timeline_rename_edges (project_root, new_symbol_id);
```

WAL mode enabled on connect (`PRAGMA journal_mode = WAL`) — same pattern as `libs/scan_history/store.py`.

### Size bounds

| Scale | Events | Snapshots | Rename edges | Total |
|-------|-------:|----------:|-------------:|------:|
| LV_DCP (5k symbols) | ~25k (5× churn) | ~10 | ~100 | ~10 MB |
| Mid corp (50k symbols) | ~500k | ~50 | ~2k | ~150 MB |
| Large corp (200k symbols) | ~4M | ~200 | ~10k | ~1.2 GB |

Retention prune (per-project, opt-in via `TimelineConfig.retention_days`) срабатывает на `append_event` так же, как `scan_history`.

## 2. Python dataclasses

### `libs/symbol_timeline/store.py`

```python
@dataclass(frozen=True)
class TimelineEvent:
    project_root: str
    symbol_id: str
    event_type: str          # added | modified | removed | renamed | moved
    commit_sha: str | None
    timestamp: float
    author: str | None
    content_hash: str | None
    file_path: str
    qualified_name: str | None = None
    extra_json: str | None = None
    orphaned: bool = False
```

### `libs/symbol_timeline/differ.py`

```python
@dataclass(frozen=True)
class SymbolSnapshot:
    symbol_id: str
    file_path: str
    content_hash: str
    qualified_name: str | None = None

@dataclass(frozen=True)
class AstSnapshot:
    symbols: Mapping[str, SymbolSnapshot]  # keyed by symbol_id
    commit_sha: str | None
```

### `libs/symbol_timeline/rename_detect.py`

```python
@dataclass(frozen=True)
class RenameEdge:
    old_symbol_id: str
    new_symbol_id: str
    confidence: float  # 0.0..1.0
    commit_sha: str | None
    timestamp: float
    is_candidate: bool  # True when similarity < 1.0
```

### `libs/symbol_timeline/snapshot.py` (Phase 6)

```python
@dataclass(frozen=True)
class ReleaseSnapshot:
    snapshot_id: str
    project_root: str
    tag: str
    head_sha: str
    timestamp: float
    symbol_count: int
    checksum: str
    tag_invalidated: bool = False
    ref_kind: str = "git_tag"
```

## 3. `TimelineSink` Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class TimelineSink(Protocol):
    """Consumer of timeline events emitted by the scanner.

    Lifecycle per scan:
      on_scan_begin
        { on_added | on_modified | on_removed | on_renamed | on_moved } *
      on_scan_end                              (called in `finally`)

    Implementations MUST be idempotent per (event.symbol_id, event.commit_sha):
    re-delivery of the same event from a retried scan should not duplicate rows.
    """

    def on_scan_begin(
        self, *, project_root: str, commit_sha: str | None, started_at: float
    ) -> None: ...

    def on_scan_end(
        self, *, project_root: str, commit_sha: str | None, stats: Mapping[str, int]
    ) -> None: ...

    def on_added(self, event: TimelineEvent) -> None: ...
    def on_modified(self, event: TimelineEvent) -> None: ...
    def on_removed(self, event: TimelineEvent) -> None: ...
    def on_moved(self, event: TimelineEvent) -> None: ...

    def on_renamed(
        self,
        *,
        project_root: str,
        old_symbol_id: str,
        new_symbol_id: str,
        commit_sha: str | None,
        timestamp: float,
        confidence: float,
        is_candidate: bool,
    ) -> None: ...
```

Two reference implementations ship:
- `SqliteTimelineSink` — wraps the store; default, ACID per-event.
- `MemoryTimelineSink` — in-memory list, for unit tests and dry-run.

Third-party sinks register via `TimelineConfig.sink_plugins = ["my_pkg.my_sink:MySink"]` (Phase 7).

## 4. `TimelineConfig` (in `libs/core/projects_config.py`)

Already documented in plan.md. Lives under `DaemonConfig.timeline`.

## 5. Invariants

1. **`symbol_id` stability**: `sha256(project_root_abs | file_path | qualified_name | kind)[:32]`. Computed once per symbol per scan. Переживает `modified`, НЕ переживает `renamed` / `moved` (новый file_path → новый id).
2. **Event ordering**: per-`(project_root, symbol_id)` events монотонны по `timestamp`. Атомарность — один scan = один batch с одним `timestamp`.
3. **`orphaned=True`** никогда не удаляет событие. Только meta-флаг, который скрывает событие из default-ответов MCP tools (фильтр `include_orphaned=False`).
4. **`rename_edges`** дополняют, не заменяют: при подтверждённом rename есть одна запись в `rename_edges` + два события (`removed` старого id, `added` нового id) с флагом `extra_json.rename_edge_id`.
5. **Snapshots immutable**: после вставки `tag_invalidated=1` возможен, но `head_sha` / `checksum` не меняется.

## 6. Indexing strategy

Все горячие запросы MCP-tools покрыты индексами:

| Query | Index |
|-------|-------|
| `lvdcp_when(symbol_id)` → `WHERE project_root=? AND symbol_id=? ORDER BY timestamp` | `idx_tle_root_symbol_ts` |
| `lvdcp_removed_since(ref)` → `WHERE project_root=? AND event_type='removed' AND timestamp>=ref_ts` | `idx_tle_root_type_ts` |
| `lvdcp_diff(from, to)` → `WHERE project_root=? AND timestamp BETWEEN ? AND ?` | `idx_tle_root_ts` |
| `reconcile` → `WHERE project_root=? AND commit_sha IN (orphaned_set)` | `idx_tle_root_commit` |

p95 < 50 ms на 500k событий (SC-002) — проверяется в Phase 8 perf-тесте.
