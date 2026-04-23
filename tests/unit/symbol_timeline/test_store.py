"""Unit tests for libs/symbol_timeline/store.py (spec-010 T005 + T009)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from libs.symbol_timeline.store import (
    RenameEdgeRow,
    SnapshotRow,
    SymbolTimelineStore,
    TimelineEvent,
    append_event,
    append_rename_edge,
    events_between,
    events_for_symbol,
    insert_snapshot,
    latest_snapshot,
    resolve_default_store_path,
)


def _event(
    *,
    project_root: str = "/abs/proj",
    symbol_id: str = "sym1",
    event_type: str = "added",
    commit_sha: str | None = "abc123",
    timestamp: float | None = None,
    file_path: str = "libs/foo.py",
    **kw: object,
) -> TimelineEvent:
    if timestamp is None:
        timestamp = time.time()
    return TimelineEvent(
        project_root=project_root,
        symbol_id=symbol_id,
        event_type=event_type,
        commit_sha=commit_sha,
        timestamp=timestamp,
        author=kw.get("author"),  # type: ignore[arg-type]
        content_hash=kw.get("content_hash", "hash-A"),  # type: ignore[arg-type]
        file_path=file_path,
        qualified_name=kw.get("qualified_name"),  # type: ignore[arg-type]
        extra_json=kw.get("extra_json"),  # type: ignore[arg-type]
        orphaned=bool(kw.get("orphaned", False)),
    )


def _fresh_store(tmp_path: Path) -> SymbolTimelineStore:
    store = SymbolTimelineStore(tmp_path / "tl.db")
    store.migrate()
    return store


class TestAppendAndQuery:
    def test_append_and_read_single_event(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        ev = _event(symbol_id="s1", event_type="added")
        append_event(store, event=ev)

        got = events_for_symbol(store, project_root="/abs/proj", symbol_id="s1")
        assert len(got) == 1
        assert got[0].event_type == "added"
        assert got[0].file_path == "libs/foo.py"

    def test_invalid_event_type_rejected(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        with pytest.raises(ValueError, match="invalid event_type"):
            append_event(store, event=_event(event_type="exploded"))

    def test_events_between_filters_timestamp(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        now = time.time()
        append_event(store, event=_event(symbol_id="s1", timestamp=now - 100.0))
        append_event(store, event=_event(symbol_id="s2", timestamp=now - 10.0))
        append_event(store, event=_event(symbol_id="s3", timestamp=now))

        got = events_between(
            store,
            project_root="/abs/proj",
            from_ts=now - 50.0,
            to_ts=now + 1.0,
        )
        assert {e.symbol_id for e in got} == {"s2", "s3"}

    def test_events_between_filters_event_types(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        now = time.time()
        append_event(store, event=_event(symbol_id="s1", event_type="added", timestamp=now))
        append_event(store, event=_event(symbol_id="s1", event_type="removed", timestamp=now))
        append_event(store, event=_event(symbol_id="s2", event_type="modified", timestamp=now))

        removed = events_between(
            store,
            project_root="/abs/proj",
            from_ts=0,
            to_ts=now + 1,
            event_types=["removed"],
        )
        assert len(removed) == 1
        assert removed[0].symbol_id == "s1"

    def test_project_root_isolation(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        append_event(store, event=_event(project_root="/abs/a", symbol_id="sA"))
        append_event(store, event=_event(project_root="/abs/b", symbol_id="sB"))

        a_got = events_between(store, project_root="/abs/a", from_ts=0, to_ts=time.time() + 1)
        b_got = events_between(store, project_root="/abs/b", from_ts=0, to_ts=time.time() + 1)
        assert len(a_got) == 1 and a_got[0].symbol_id == "sA"
        assert len(b_got) == 1 and b_got[0].symbol_id == "sB"


class TestRetention:
    def test_retention_prunes_old_events(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        now = time.time()
        append_event(
            store,
            event=_event(symbol_id="old", timestamp=now - 100 * 86400),
            retention_days=30,
        )
        append_event(
            store,
            event=_event(symbol_id="recent", timestamp=now - 10 * 86400),
            retention_days=30,
        )

        got = events_between(store, project_root="/abs/proj", from_ts=0, to_ts=now + 1)
        assert {e.symbol_id for e in got} == {"recent"}

    def test_retention_none_keeps_everything(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        now = time.time()
        append_event(
            store,
            event=_event(symbol_id="old", timestamp=now - 1000 * 86400),
            retention_days=None,
        )
        got = events_between(store, project_root="/abs/proj", from_ts=0, to_ts=now + 1)
        assert len(got) == 1


class TestOrphaned:
    def test_orphaned_hidden_by_default(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        append_event(
            store,
            event=_event(symbol_id="o", orphaned=True),
        )
        assert events_for_symbol(store, project_root="/abs/proj", symbol_id="o") == []

    def test_orphaned_returned_when_opt_in(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        append_event(
            store,
            event=_event(symbol_id="o", orphaned=True),
        )
        got = events_for_symbol(
            store,
            project_root="/abs/proj",
            symbol_id="o",
            include_orphaned=True,
        )
        assert len(got) == 1 and got[0].orphaned


class TestSnapshots:
    def test_insert_and_fetch_latest(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        row = SnapshotRow(
            snapshot_id="snap1",
            project_root="/abs/proj",
            tag="v1.0",
            head_sha="deadbeef",
            timestamp=time.time(),
            symbol_count=42,
            checksum="chksum-1",
        )
        insert_snapshot(store, snapshot=row)

        got = latest_snapshot(store, project_root="/abs/proj", tag="v1.0")
        assert got is not None
        assert got.snapshot_id == "snap1"
        assert got.symbol_count == 42

    def test_snapshot_id_idempotent(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        row = SnapshotRow(
            snapshot_id="same",
            project_root="/abs/proj",
            tag="v1.0",
            head_sha="hA",
            timestamp=10.0,
            symbol_count=1,
            checksum="c",
        )
        insert_snapshot(store, snapshot=row)
        # Second insert with same snapshot_id is a no-op (INSERT OR IGNORE).
        insert_snapshot(store, snapshot=row)
        got = latest_snapshot(store, project_root="/abs/proj", tag="v1.0")
        assert got is not None and got.snapshot_id == "same"

    def test_latest_snapshot_none_when_absent(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        assert latest_snapshot(store, project_root="/abs/x", tag="never") is None


class TestRenameEdges:
    def test_append_and_round_trip(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        append_rename_edge(
            store,
            edge=RenameEdgeRow(
                project_root="/abs/proj",
                old_symbol_id="old",
                new_symbol_id="new",
                commit_sha="sha1",
                timestamp=10.0,
                confidence=0.95,
                is_candidate=False,
            ),
        )
        conn = store._connect()
        rows = conn.execute(
            "SELECT old_symbol_id, new_symbol_id, confidence, is_candidate "
            "FROM symbol_timeline_rename_edges"
        ).fetchall()
        assert rows == [("old", "new", 0.95, 0)]


class TestEnvOverride:
    def test_env_override_honored(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        override = tmp_path / "custom.db"
        monkeypatch.setenv("LVDCP_TIMELINE_DB", str(override))
        assert resolve_default_store_path() == override

    def test_no_override_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LVDCP_TIMELINE_DB", raising=False)
        got = resolve_default_store_path()
        assert str(got).endswith("/.lvdcp/symbol_timeline.db")


class TestConfig:
    def test_timeline_config_defaults(self) -> None:
        from libs.core.projects_config import DaemonConfig, TimelineConfig

        cfg = DaemonConfig()
        assert isinstance(cfg.timeline, TimelineConfig)
        assert cfg.timeline.enabled is True
        assert cfg.timeline.rename_similarity_threshold == 0.85
        assert cfg.timeline.privacy_mode == "balanced"
        assert cfg.timeline.retention_days is None

    def test_privacy_mode_validator_rejects_garbage(self) -> None:
        from libs.core.projects_config import TimelineConfig

        with pytest.raises(ValueError, match="privacy_mode must be one of"):
            TimelineConfig(privacy_mode="yolo")

    def test_rename_threshold_bounds(self) -> None:
        from libs.core.projects_config import TimelineConfig

        with pytest.raises(ValueError):
            TimelineConfig(rename_similarity_threshold=1.5)
        with pytest.raises(ValueError):
            TimelineConfig(rename_similarity_threshold=-0.1)
