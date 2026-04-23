"""Unit tests for libs/symbol_timeline/sinks.py (spec-010 T006 + T009)."""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.symbol_timeline.rename_detect import RenameEdge
from libs.symbol_timeline.sinks import (
    MemoryTimelineSink,
    SqliteTimelineSink,
    TimelineSink,
)
from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    events_for_symbol,
)


def _ev(event_type: str, symbol_id: str = "s1") -> TimelineEvent:
    return TimelineEvent(
        project_root="/abs/p",
        symbol_id=symbol_id,
        event_type=event_type,
        commit_sha="sha1",
        timestamp=1.0,
        author=None,
        content_hash="H",
        file_path="libs/a.py",
    )


class TestProtocolConformance:
    def test_memory_sink_satisfies_protocol(self) -> None:
        sink = MemoryTimelineSink()
        assert isinstance(sink, TimelineSink)

    def test_sqlite_sink_satisfies_protocol(self, tmp_path: Path) -> None:
        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)
        assert isinstance(sink, TimelineSink)


class TestMemorySink:
    def test_records_lifecycle(self) -> None:
        sink = MemoryTimelineSink()
        sink.on_scan_begin(project_root="/abs/p", commit_sha="abc", started_at=10.0)
        sink.on_added(_ev("added", "a"))
        sink.on_modified(_ev("modified", "b"))
        sink.on_removed(_ev("removed", "c"))
        sink.on_moved(_ev("moved", "d"))
        sink.on_scan_end(
            project_root="/abs/p",
            commit_sha="abc",
            stats={"added": 1, "modified": 1, "removed": 1, "moved": 1},
        )

        assert sink.begins == [("/abs/p", "abc", 10.0)]
        assert len(sink.ends) == 1
        assert sink.ends[0][2] == {"added": 1, "modified": 1, "removed": 1, "moved": 1}
        assert {e.symbol_id for e in sink.events} == {"a", "b", "c", "d"}

    def test_events_of_type_filters(self) -> None:
        sink = MemoryTimelineSink()
        sink.on_added(_ev("added", "a"))
        sink.on_removed(_ev("removed", "b"))
        sink.on_added(_ev("added", "c"))

        assert [e.symbol_id for e in sink.events_of_type("added")] == ["a", "c"]
        assert [e.symbol_id for e in sink.events_of_type("removed")] == ["b"]

    def test_on_renamed_stores_edge(self) -> None:
        sink = MemoryTimelineSink()
        edge = RenameEdge(
            old_symbol_id="o",
            new_symbol_id="n",
            confidence=0.9,
            commit_sha="sha1",
            timestamp=1.0,
            is_candidate=True,
        )
        sink.on_renamed(edge, project_root="/abs/p")
        assert sink.edges == [edge]

    def test_stats_snapshot_not_aliased(self) -> None:
        """Mutating stats after on_scan_end must not leak into recorded state."""
        sink = MemoryTimelineSink()
        stats: dict[str, int] = {"added": 1}
        sink.on_scan_end(project_root="/abs/p", commit_sha=None, stats=stats)
        stats["added"] = 99
        assert sink.ends[0][2] == {"added": 1}


class TestSqliteSink:
    def test_append_event_lands_in_store(self, tmp_path: Path) -> None:
        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)

        sink.on_added(_ev("added", "x"))
        got = events_for_symbol(store, project_root="/abs/p", symbol_id="x")
        assert len(got) == 1 and got[0].event_type == "added"

    def test_all_event_methods_persist(self, tmp_path: Path) -> None:
        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)

        sink.on_added(_ev("added", "a"))
        sink.on_modified(_ev("modified", "a"))
        sink.on_moved(_ev("moved", "a"))
        sink.on_removed(_ev("removed", "a"))

        got = events_for_symbol(store, project_root="/abs/p", symbol_id="a")
        assert [e.event_type for e in got] == ["added", "modified", "moved", "removed"]

    def test_on_renamed_persists_edge(self, tmp_path: Path) -> None:
        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)

        edge = RenameEdge(
            old_symbol_id="o",
            new_symbol_id="n",
            confidence=0.9,
            commit_sha="sha1",
            timestamp=1.0,
            is_candidate=True,
        )
        sink.on_renamed(edge, project_root="/abs/p")

        conn = store._connect()
        rows = conn.execute(
            "SELECT old_symbol_id, new_symbol_id, confidence, is_candidate "
            "FROM symbol_timeline_rename_edges"
        ).fetchall()
        assert rows == [("o", "n", 0.9, 1)]

    def test_retention_wired_through_sink(self, tmp_path: Path) -> None:
        import time as _time

        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store, retention_days=30)

        now = _time.time()
        old_ev = TimelineEvent(
            project_root="/abs/p",
            symbol_id="old",
            event_type="added",
            commit_sha=None,
            timestamp=now - 100 * 86400,
            author=None,
            content_hash="H",
            file_path="a.py",
        )
        fresh_ev = TimelineEvent(
            project_root="/abs/p",
            symbol_id="fresh",
            event_type="added",
            commit_sha=None,
            timestamp=now,
            author=None,
            content_hash="H",
            file_path="a.py",
        )
        sink.on_added(old_ev)
        sink.on_added(fresh_ev)

        conn = store._connect()
        rows = conn.execute(
            "SELECT symbol_id FROM symbol_timeline_events ORDER BY symbol_id"
        ).fetchall()
        assert [r[0] for r in rows] == ["fresh"]


class TestSqliteSinkMetricsInstrumentation:
    """T038 — SqliteTimelineSink must bump events_total + sink_errors_total."""

    def test_on_added_bumps_events_total(self, tmp_path: Path) -> None:
        from libs.telemetry import timeline_metrics as tm

        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)

        before = tm.events_total.labels(event_type="added", project="/abs/p").value()
        sink.on_added(_ev("added", "m1"))
        after = tm.events_total.labels(event_type="added", project="/abs/p").value()
        assert after - before == 1

    def test_each_event_method_uses_its_own_label(self, tmp_path: Path) -> None:
        from libs.telemetry import timeline_metrics as tm

        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)

        snaps_before = {
            kind: tm.events_total.labels(event_type=kind, project="/abs/p").value()
            for kind in ("added", "modified", "removed", "moved")
        }
        sink.on_added(_ev("added", "a"))
        sink.on_modified(_ev("modified", "a"))
        sink.on_removed(_ev("removed", "a"))
        sink.on_moved(_ev("moved", "a"))
        for kind in ("added", "modified", "removed", "moved"):
            delta = (
                tm.events_total.labels(event_type=kind, project="/abs/p").value()
                - snaps_before[kind]
            )
            assert delta == 1, f"{kind} was not incremented exactly once"

    def test_append_failure_bumps_sink_errors_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``append_event`` raises, the metric must tick up and the error re-raises."""
        from libs.symbol_timeline import sinks as _sinks
        from libs.telemetry import timeline_metrics as tm

        store = SymbolTimelineStore(tmp_path / "t.db")
        store.migrate()
        sink = SqliteTimelineSink(store=store)

        def boom(*_args: object, **_kwargs: object) -> None:
            msg = "simulated disk-full"
            raise OSError(msg)

        monkeypatch.setattr(_sinks, "append_event", boom)

        before = tm.sink_errors_total.labels(sink="sqlite", stage="on_added").value()
        with pytest.raises(OSError, match="simulated disk-full"):
            sink.on_added(_ev("added", "err"))
        after = tm.sink_errors_total.labels(sink="sqlite", stage="on_added").value()
        assert after - before == 1


class TestFixtureWiring:
    def test_memory_timeline_sink_fixture_fresh_each_test(
        self, memory_timeline_sink: MemoryTimelineSink
    ) -> None:
        assert memory_timeline_sink.events == []
        memory_timeline_sink.on_added(_ev("added", "fx"))
        assert len(memory_timeline_sink.events) == 1

    def test_tmp_git_repo_fixture_creates_repo(self, tmp_git_repo) -> None:  # type: ignore[no-untyped-def]
        tmp_git_repo.write("hello.py", "print('hi')\n")
        sha = tmp_git_repo.commit("initial")
        assert len(sha) == 40  # full SHA
        # Tag creation.
        tmp_git_repo.tag("v0.1")
        result = tmp_git_repo.run("tag", "--list")
        assert "v0.1" in result.stdout
