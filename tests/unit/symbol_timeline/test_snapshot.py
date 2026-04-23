"""Unit tests for libs/symbol_timeline/snapshot.py (spec-010 T026)."""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.gitintel.tag_watcher import TagEvent
from libs.symbol_timeline.differ import AstSnapshot, SymbolSnapshot
from libs.symbol_timeline.snapshot import (
    build_release_snapshot,
    compute_snapshot_checksum,
    compute_snapshot_id,
    handle_tag_event,
    invalidate_existing_tag,
)
from libs.symbol_timeline.snapshot_builder import PREV_SNAPSHOT_RELPATH, save_snapshot
from libs.symbol_timeline.store import SymbolTimelineStore, latest_snapshot

PROJECT = "/abs/proj"


@pytest.fixture
def store(tmp_path: Path) -> SymbolTimelineStore:
    s = SymbolTimelineStore(tmp_path / "timeline.db")
    s.migrate()
    return s


def test_snapshot_id_is_deterministic_and_collision_free() -> None:
    a = compute_snapshot_id(PROJECT, "v1", "sha-head-1")
    b = compute_snapshot_id(PROJECT, "v1", "sha-head-1")
    c = compute_snapshot_id(PROJECT, "v1", "sha-head-2")
    d = compute_snapshot_id(PROJECT, "v2", "sha-head-1")
    assert a == b
    assert a != c
    assert a != d
    assert len(a) == 32


def test_checksum_is_order_independent() -> None:
    a = compute_snapshot_checksum(["s1", "s2", "s3"])
    b = compute_snapshot_checksum(["s3", "s1", "s2"])
    assert a == b
    # Different set → different checksum
    c = compute_snapshot_checksum(["s1", "s2"])
    assert a != c


def test_build_release_snapshot_from_explicit_symbol_ids(
    store: SymbolTimelineStore,
) -> None:
    row = build_release_snapshot(
        store,
        project_root=PROJECT,
        tag="v1",
        head_sha="headsha123",
        symbol_ids=["a" * 32, "b" * 32, "c" * 32],
        now=1000.0,
    )
    assert row.tag == "v1"
    assert row.head_sha == "headsha123"
    assert row.symbol_count == 3
    assert row.tag_invalidated is False
    assert row.ref_kind == "git_tag"

    stored = latest_snapshot(store, project_root=PROJECT, tag="v1")
    assert stored is not None
    assert stored.snapshot_id == row.snapshot_id
    assert stored.checksum == row.checksum


def test_build_release_snapshot_is_idempotent(store: SymbolTimelineStore) -> None:
    """Same (project, tag, head_sha) twice → one row (INSERT OR IGNORE)."""

    def _call() -> None:
        build_release_snapshot(
            store,
            project_root=PROJECT,
            tag="v1",
            head_sha="headsha",
            symbol_ids=["a" * 32],
            now=1000.0,
        )

    _call()
    _call()
    rows = (
        store._connect()
        .execute(
            "SELECT COUNT(*) FROM symbol_timeline_snapshots WHERE project_root = ? AND tag = ?",
            (PROJECT, "v1"),
        )
        .fetchone()
    )
    assert rows[0] == 1


def test_build_release_snapshot_reads_sidecar_when_symbol_ids_omitted(
    store: SymbolTimelineStore, tmp_path: Path
) -> None:
    """With no explicit symbol_ids, we pick them up from timeline_prev.json."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    ids = ["x" * 32, "y" * 32]
    snap = AstSnapshot(
        symbols={
            sid: SymbolSnapshot(symbol_id=sid, file_path="f.py", content_hash="h") for sid in ids
        },
        commit_sha="headsha",
    )
    save_snapshot(snap, path=project_dir / PREV_SNAPSHOT_RELPATH)

    row = build_release_snapshot(
        store,
        project_root=str(project_dir),
        tag="v1",
        head_sha="headsha",
        sidecar_root=project_dir,
    )
    assert row.symbol_count == 2
    assert row.checksum == compute_snapshot_checksum(ids)


def test_build_release_snapshot_handles_missing_sidecar(
    store: SymbolTimelineStore, tmp_path: Path
) -> None:
    """No sidecar file → empty snapshot (symbol_count=0) rather than crash."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    row = build_release_snapshot(
        store,
        project_root=str(project_dir),
        tag="v1",
        head_sha="headsha",
        sidecar_root=project_dir,
    )
    assert row.symbol_count == 0


def test_invalidate_existing_tag_flips_old_row(store: SymbolTimelineStore) -> None:
    """Re-creating ``v1`` at a different commit flags the prior row."""
    build_release_snapshot(
        store,
        project_root=PROJECT,
        tag="v1",
        head_sha="old-head",
        symbol_ids=["a" * 32],
        now=1000.0,
    )
    flipped = invalidate_existing_tag(
        store, project_root=PROJECT, tag="v1", current_head_sha="new-head"
    )
    assert flipped == 1

    rows = (
        store._connect()
        .execute(
            "SELECT tag_invalidated FROM symbol_timeline_snapshots "
            "WHERE project_root = ? AND tag = ?",
            (PROJECT, "v1"),
        )
        .fetchall()
    )
    assert rows == [(1,)]

    # Now insert a fresh snapshot at new-head; old one stays invalidated.
    build_release_snapshot(
        store,
        project_root=PROJECT,
        tag="v1",
        head_sha="new-head",
        symbol_ids=["a" * 32],
        now=2000.0,
    )
    total = (
        store._connect()
        .execute(
            "SELECT COUNT(*), SUM(tag_invalidated) FROM symbol_timeline_snapshots "
            "WHERE project_root = ? AND tag = ?",
            (PROJECT, "v1"),
        )
        .fetchone()
    )
    assert total == (2, 1)  # 2 rows total, 1 invalidated


def test_invalidate_noop_when_head_sha_unchanged(store: SymbolTimelineStore) -> None:
    build_release_snapshot(
        store,
        project_root=PROJECT,
        tag="v1",
        head_sha="same-head",
        symbol_ids=[],
        now=1000.0,
    )
    flipped = invalidate_existing_tag(
        store, project_root=PROJECT, tag="v1", current_head_sha="same-head"
    )
    assert flipped == 0


def test_handle_tag_event_created_inserts_new_row(store: SymbolTimelineStore) -> None:
    event = TagEvent(tag="v1", head_sha="sha-v1", kind="created")
    row = handle_tag_event(
        store,
        project_root=PROJECT,
        event=event,
        symbol_ids=["a" * 32],
        now=1000.0,
    )
    assert row.tag == "v1"
    assert row.head_sha == "sha-v1"
    assert row.tag_invalidated is False


def test_handle_tag_event_moved_invalidates_prior_and_inserts_new(
    store: SymbolTimelineStore,
) -> None:
    # Seed with the old snapshot
    handle_tag_event(
        store,
        project_root=PROJECT,
        event=TagEvent(tag="v1", head_sha="old-sha", kind="created"),
        symbol_ids=["a" * 32],
        now=1000.0,
    )
    # Now the tag moved to a new commit
    new_row = handle_tag_event(
        store,
        project_root=PROJECT,
        event=TagEvent(tag="v1", head_sha="new-sha", kind="moved", previous_sha="old-sha"),
        symbol_ids=["a" * 32],
        now=2000.0,
    )
    assert new_row.head_sha == "new-sha"
    assert new_row.tag_invalidated is False
    # Old row flipped to invalidated=1
    rows = (
        store._connect()
        .execute(
            "SELECT head_sha, tag_invalidated FROM symbol_timeline_snapshots "
            "WHERE project_root = ? AND tag = ? ORDER BY timestamp",
            (PROJECT, "v1"),
        )
        .fetchall()
    )
    assert rows == [("old-sha", 1), ("new-sha", 0)]
