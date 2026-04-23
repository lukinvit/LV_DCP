"""Release snapshots — immutable anchors for each git tag (spec FR-005).

Distinct from the scan-to-scan sidecar :mod:`libs.symbol_timeline.snapshot_builder`:

* ``snapshot_builder`` writes the *previous* AstSnapshot to ``.context/
  timeline_prev.json`` so the next scan can diff against it.
* ``snapshot`` (this module) writes an *immutable release snapshot* to the
  ``symbol_timeline_snapshots`` table when ``tag_watcher`` observes a new
  tag. The row is a fingerprint — ``(tag, head_sha, symbol_count, checksum)``
  — that ``lvdcp_diff`` can cheaply compare against another snapshot to
  detect "nothing changed" before falling back to event replay.

Identity rules (spec §Edge Cases):

* ``snapshot_id = sha256(project_root | tag | head_sha)[:32]`` — two tags
  pointing at the same commit share nothing; re-creating the same tag at a
  different commit produces a new id AND marks the prior row
  ``tag_invalidated=1``.
* ``checksum = sha256(sorted symbol_ids)`` — a cheap content anchor used to
  detect "snapshot drift" without loading the full symbol set.

Spec: specs/010-feature-timeline-index/data-model.md §1 + §5.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING

from libs.symbol_timeline.snapshot_builder import PREV_SNAPSHOT_RELPATH, load_snapshot
from libs.symbol_timeline.store import SnapshotRow, SymbolTimelineStore, insert_snapshot
from libs.telemetry.timeline_metrics import observe_snapshot_build

if TYPE_CHECKING:
    from libs.gitintel.tag_watcher import TagEvent
    from libs.symbol_timeline.differ import AstSnapshot


def compute_snapshot_id(project_root: str, tag: str, head_sha: str) -> str:
    """Deterministic 32-hex id — spec data-model §1."""
    payload = f"{project_root}\0{tag}\0{head_sha}".encode()
    return hashlib.sha256(payload).hexdigest()[:32]


def compute_snapshot_checksum(symbol_ids: list[str]) -> str:
    """sha256 over the sorted ``symbol_id`` set — full 64-hex (data-model §1)."""
    digest = hashlib.sha256()
    for sid in sorted(symbol_ids):
        digest.update(sid.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def build_release_snapshot(  # noqa: PLR0913 - keyword-only snapshot API
    store: SymbolTimelineStore,
    *,
    project_root: str,
    tag: str,
    head_sha: str,
    symbol_ids: list[str] | None = None,
    sidecar_root: Path | None = None,
    now: float | None = None,
) -> SnapshotRow:
    """Persist an immutable release snapshot for ``(tag, head_sha)``.

    ``symbol_ids`` is the authoritative symbol set to fingerprint. When
    omitted, we read them from ``sidecar_root/.context/timeline_prev.json``
    (the most recent scan's snapshot) — convenient for tag_watcher which
    doesn't have direct access to the scanner cache.

    The function is idempotent: re-running it with the same
    ``(project_root, tag, head_sha)`` inserts nothing (``INSERT OR IGNORE``)
    and returns the row that would have been inserted. Callers who need to
    detect drift can compare the returned ``checksum`` against the stored
    row.
    """
    with observe_snapshot_build():
        if symbol_ids is None:
            if sidecar_root is None:
                sidecar_root = Path(project_root)
            snap: AstSnapshot | None = load_snapshot(sidecar_root / PREV_SNAPSHOT_RELPATH)
            symbol_ids = list(snap.symbols.keys()) if snap is not None else []

        snapshot_id = compute_snapshot_id(project_root, tag, head_sha)
        checksum = compute_snapshot_checksum(symbol_ids)
        ts = now if now is not None else time.time()

        row = SnapshotRow(
            project_root=project_root,
            snapshot_id=snapshot_id,
            tag=tag,
            head_sha=head_sha,
            timestamp=ts,
            symbol_count=len(symbol_ids),
            checksum=checksum,
            tag_invalidated=False,
            ref_kind="git_tag",
        )
        insert_snapshot(store, snapshot=row)
    return row


def invalidate_existing_tag(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    tag: str,
    current_head_sha: str,
) -> int:
    """Flag prior snapshots for ``tag`` that no longer match ``current_head_sha``.

    Called by tag_watcher when it detects a tag that was *re-created* at a
    different commit (delete + re-tag). The old rows stay for audit but
    their ``tag_invalidated`` flag becomes ``1`` so queries can drop them.

    Returns the number of rows flipped.
    """
    conn = store._connect()
    cur = conn.execute(
        "UPDATE symbol_timeline_snapshots SET tag_invalidated = 1 "
        "WHERE project_root = ? AND tag = ? AND head_sha != ? "
        "AND tag_invalidated = 0",
        (project_root, tag, current_head_sha),
    )
    conn.commit()
    return cur.rowcount or 0


def handle_tag_event(  # noqa: PLR0913 - keyword-only snapshot API
    store: SymbolTimelineStore,
    *,
    project_root: str,
    event: TagEvent,
    sidecar_root: Path | None = None,
    symbol_ids: list[str] | None = None,
    now: float | None = None,
) -> SnapshotRow:
    """Apply one :class:`TagEvent` from :mod:`libs.gitintel.tag_watcher`.

    For ``kind="created"`` — just build a new snapshot.
    For ``kind="moved"``   — flag prior snapshots of the same tag
    (``tag_invalidated=1``) then insert a fresh row at the new head_sha.

    The result is always the newly-inserted row (or the pre-existing row
    if the call is idempotent), so the caller can log the ``snapshot_id``
    and ``symbol_count``.
    """
    if event.kind == "moved":
        invalidate_existing_tag(
            store,
            project_root=project_root,
            tag=event.tag,
            current_head_sha=event.head_sha,
        )
    return build_release_snapshot(
        store,
        project_root=project_root,
        tag=event.tag,
        head_sha=event.head_sha,
        symbol_ids=symbol_ids,
        sidecar_root=sidecar_root,
        now=now,
    )


__all__ = [
    "build_release_snapshot",
    "compute_snapshot_checksum",
    "compute_snapshot_id",
    "handle_tag_event",
    "invalidate_existing_tag",
]
