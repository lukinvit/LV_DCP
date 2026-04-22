"""Unit tests for libs/symbol_timeline/differ.py (spec-010 T007 + T009)."""

from __future__ import annotations

import json

from libs.symbol_timeline.differ import (
    AstSnapshot,
    SymbolSnapshot,
    diff_ast_snapshots,
)


def _snap(*symbols: SymbolSnapshot, commit_sha: str | None = "curr_sha") -> AstSnapshot:
    return AstSnapshot(
        symbols={s.symbol_id: s for s in symbols},
        commit_sha=commit_sha,
    )


def _sym(
    symbol_id: str,
    *,
    file_path: str = "libs/a.py",
    content_hash: str = "hA",
    qualified_name: str | None = None,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol_id=symbol_id,
        file_path=file_path,
        content_hash=content_hash,
        qualified_name=qualified_name,
    )


class TestBasicTransitions:
    def test_added_when_only_in_curr(self) -> None:
        prev = _snap()
        curr = _snap(_sym("s1"))

        events = list(diff_ast_snapshots(prev, curr, project_root="/abs/p", timestamp=1.0))
        assert len(events) == 1
        assert events[0].event_type == "added"
        assert events[0].symbol_id == "s1"
        assert events[0].commit_sha == "curr_sha"

    def test_removed_when_only_in_prev(self) -> None:
        prev = _snap(_sym("s1"))
        curr = _snap()

        events = list(diff_ast_snapshots(prev, curr, project_root="/abs/p", timestamp=1.0))
        assert len(events) == 1
        assert events[0].event_type == "removed"
        # Removed event inherits last-seen file_path from prev.
        assert events[0].file_path == "libs/a.py"

    def test_unchanged_produces_no_event(self) -> None:
        s = _sym("s1", content_hash="hX", file_path="libs/a.py")
        events = list(diff_ast_snapshots(_snap(s), _snap(s), project_root="/abs/p", timestamp=1.0))
        assert events == []

    def test_modified_same_path_different_hash(self) -> None:
        prev = _snap(_sym("s1", content_hash="hA", file_path="libs/a.py"))
        curr = _snap(_sym("s1", content_hash="hB", file_path="libs/a.py"))

        events = list(diff_ast_snapshots(prev, curr, project_root="/abs/p", timestamp=1.0))
        assert len(events) == 1
        assert events[0].event_type == "modified"
        extra = json.loads(events[0].extra_json or "{}")
        assert extra == {"old_content_hash": "hA"}

    def test_moved_same_hash_different_path(self) -> None:
        prev = _snap(_sym("s1", content_hash="hX", file_path="libs/a.py"))
        curr = _snap(_sym("s1", content_hash="hX", file_path="libs/b.py"))

        events = list(diff_ast_snapshots(prev, curr, project_root="/abs/p", timestamp=1.0))
        assert len(events) == 1
        assert events[0].event_type == "moved"
        extra = json.loads(events[0].extra_json or "{}")
        assert extra == {"old_file_path": "libs/a.py"}


class TestEdges:
    def test_empty_prev_and_curr(self) -> None:
        events = list(diff_ast_snapshots(_snap(), _snap(), project_root="/abs/p", timestamp=1.0))
        assert events == []

    def test_all_removed_when_curr_empty(self) -> None:
        prev = _snap(_sym("s1"), _sym("s2"), _sym("s3"))
        curr = _snap()
        events = list(diff_ast_snapshots(prev, curr, project_root="/abs/p", timestamp=1.0))
        assert len(events) == 3
        assert all(e.event_type == "removed" for e in events)

    def test_mixed_batch(self) -> None:
        prev = _snap(
            _sym("unchanged", content_hash="h0", file_path="a.py"),
            _sym("will_mod", content_hash="h1", file_path="a.py"),
            _sym("will_move", content_hash="h2", file_path="a.py"),
            _sym("will_rm", content_hash="h3", file_path="a.py"),
        )
        curr = _snap(
            _sym("unchanged", content_hash="h0", file_path="a.py"),
            _sym("will_mod", content_hash="h1_new", file_path="a.py"),
            _sym("will_move", content_hash="h2", file_path="b.py"),
            _sym("brand_new", content_hash="h4", file_path="c.py"),
        )
        events = list(diff_ast_snapshots(prev, curr, project_root="/abs/p", timestamp=1.0))
        # Expect: 1 added, 1 removed, 1 modified, 1 moved.
        by_type = {e.event_type: e for e in events}
        assert set(by_type.keys()) == {"added", "removed", "modified", "moved"}
        assert by_type["added"].symbol_id == "brand_new"
        assert by_type["removed"].symbol_id == "will_rm"
        assert by_type["modified"].symbol_id == "will_mod"
        assert by_type["moved"].symbol_id == "will_move"

    def test_deterministic_order(self) -> None:
        # Two adds in randomized dict insertion order → events come out sorted.
        curr = _snap(
            _sym("z_sym"),
            _sym("a_sym"),
            _sym("m_sym"),
        )
        events = list(diff_ast_snapshots(_snap(), curr, project_root="/abs/p", timestamp=1.0))
        assert [e.symbol_id for e in events] == ["a_sym", "m_sym", "z_sym"]

    def test_commit_sha_stamped_from_curr(self) -> None:
        curr = _snap(_sym("s1"), commit_sha="NEW_HEAD")
        events = list(diff_ast_snapshots(_snap(), curr, project_root="/abs/p", timestamp=1.0))
        assert events[0].commit_sha == "NEW_HEAD"

    def test_author_flows_through(self) -> None:
        curr = _snap(_sym("s1"))
        events = list(
            diff_ast_snapshots(
                _snap(),
                curr,
                project_root="/abs/p",
                timestamp=1.0,
                author="someone@example.com",
            )
        )
        assert events[0].author == "someone@example.com"
