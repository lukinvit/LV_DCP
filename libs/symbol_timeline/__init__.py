"""Symbol timeline index — append-only event store for "when was X
implemented?" and "what disappeared after release Y?" questions.

Spec: specs/010-feature-timeline-index/
"""

from libs.symbol_timeline.query import (
    RemovedSinceResult,
    RemovedSymbol,
    RenamePair,
    find_removed_since,
    resolve_git_ref,
)
from libs.symbol_timeline.snapshot_builder import (
    PREV_SNAPSHOT_RELPATH,
    build_snapshot_from_cache,
    build_snapshot_from_symbols,
    compute_symbol_content_hash,
    compute_symbol_id,
    load_snapshot,
    save_snapshot,
)
from libs.symbol_timeline.store import (
    DEFAULT_STORE_PATH,
    RenameEdgeRow,
    ScanState,
    SnapshotRow,
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
    append_rename_edge,
    events_between,
    events_for_symbol,
    get_scan_state,
    insert_snapshot,
    latest_snapshot,
    reconcile_orphaned_events,
    resolve_default_store_path,
    upsert_scan_state,
)

__all__ = [
    "DEFAULT_STORE_PATH",
    "PREV_SNAPSHOT_RELPATH",
    "RemovedSinceResult",
    "RemovedSymbol",
    "RenameEdgeRow",
    "RenamePair",
    "ScanState",
    "SnapshotRow",
    "SymbolTimelineStore",
    "TimelineEvent",
    "append_event",
    "append_rename_edge",
    "build_snapshot_from_cache",
    "build_snapshot_from_symbols",
    "compute_symbol_content_hash",
    "compute_symbol_id",
    "events_between",
    "events_for_symbol",
    "find_removed_since",
    "get_scan_state",
    "insert_snapshot",
    "latest_snapshot",
    "load_snapshot",
    "reconcile_orphaned_events",
    "resolve_default_store_path",
    "resolve_git_ref",
    "save_snapshot",
    "upsert_scan_state",
]
