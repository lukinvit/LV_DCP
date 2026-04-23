"""Unit tests for libs/symbol_timeline/rename_detect.py (spec-010 T008 + T009)."""

from __future__ import annotations

from libs.symbol_timeline.rename_detect import pair_renames
from libs.symbol_timeline.store import TimelineEvent


def _event(
    symbol_id: str,
    event_type: str,
    *,
    qualified_name: str | None = None,
    content_hash: str | None = None,
    file_path: str = "libs/a.py",
) -> TimelineEvent:
    return TimelineEvent(
        project_root="/abs/p",
        symbol_id=symbol_id,
        event_type=event_type,
        commit_sha="sha1",
        timestamp=1.0,
        author=None,
        content_hash=content_hash,
        file_path=file_path,
        qualified_name=qualified_name,
    )


class TestHighConfidencePairs:
    def test_exact_name_match_is_candidate_at_090(self) -> None:
        """Same leaf name, different paths ⇒ confidence 0.9 ⇒ is_candidate=True."""
        events = [
            _event("old_id", "removed", qualified_name="libs.a.parse"),
            _event("new_id", "added", qualified_name="libs.b.parse"),
        ]
        edges, remaining = pair_renames(events, similarity_threshold=0.85)

        assert len(edges) == 1
        assert edges[0].old_symbol_id == "old_id"
        assert edges[0].new_symbol_id == "new_id"
        assert edges[0].confidence == 0.9
        assert edges[0].is_candidate is True
        # At 0.9 confidence (is_candidate), originals stay in remaining.
        assert len(remaining) == 2

    def test_exact_content_hash_match_full_confidence(self) -> None:
        """Exact content_hash match ⇒ confidence 1.0 ⇒ originals dropped."""
        events = [
            _event("old_id", "removed", content_hash="H1"),
            _event("new_id", "added", content_hash="H1"),
        ]
        edges, remaining = pair_renames(events)

        assert len(edges) == 1
        assert edges[0].confidence == 1.0
        assert edges[0].is_candidate is False
        # Full confidence: originals consumed.
        assert remaining == []


class TestBelowThreshold:
    def test_dissimilar_names_no_pair(self) -> None:
        events = [
            _event("old_id", "removed", qualified_name="libs.a.parse_user"),
            _event("new_id", "added", qualified_name="libs.a.render_invoice"),
        ]
        edges, remaining = pair_renames(events, similarity_threshold=0.85)
        assert edges == []
        assert len(remaining) == 2  # Both kept as orphaned add/remove.

    def test_missing_qualified_name_no_pair(self) -> None:
        events = [
            _event("old_id", "removed"),
            _event("new_id", "added"),
        ]
        edges, remaining = pair_renames(events, similarity_threshold=0.85)
        assert edges == []
        assert len(remaining) == 2

    def test_threshold_gates(self) -> None:
        """Lower threshold lets a soft match through."""
        events = [
            _event("old_id", "removed", qualified_name="mod.parse_user"),
            _event("new_id", "added", qualified_name="mod.parse_account"),
        ]
        # parse_user vs parse_account — ratio ≈ 0.7, below 0.85.
        edges, _remaining = pair_renames(events, similarity_threshold=0.85)
        assert edges == []

        # With threshold 0.6 the ratio passes and we get a candidate edge.
        edges, _remaining = pair_renames(events, similarity_threshold=0.6)
        assert len(edges) == 1
        assert edges[0].is_candidate is True


class TestGreedyPairing:
    def test_one_removed_many_added_picks_best(self) -> None:
        removed = _event("r_id", "removed", qualified_name="pkg.parse")
        add_a = _event("a_id", "added", qualified_name="pkg.unrelated")
        add_b = _event("b_id", "added", qualified_name="pkg.parse")  # best

        edges, _remaining = pair_renames([removed, add_a, add_b])
        assert len(edges) == 1
        assert edges[0].new_symbol_id == "b_id"

    def test_mixed_events_other_types_preserved(self) -> None:
        events = [
            _event("old_id", "removed", qualified_name="m.foo"),
            _event("new_id", "added", content_hash="H", qualified_name="m.foo"),
            _event("mod_id", "modified"),
            _event("move_id", "moved"),
        ]
        _edges, remaining = pair_renames(events)
        # Non-add/remove events always preserved.
        types = {e.event_type for e in remaining}
        assert "modified" in types
        assert "moved" in types

    def test_consumed_added_not_reused(self) -> None:
        """A single ``added`` event cannot pair to two removals."""
        events = [
            _event("r1", "removed", content_hash="H"),
            _event("r2", "removed", content_hash="H"),
            _event("a1", "added", content_hash="H"),
        ]
        edges, _remaining = pair_renames(events)
        # Only one of r1/r2 pairs — the other stays in remaining.
        assert len(edges) == 1
