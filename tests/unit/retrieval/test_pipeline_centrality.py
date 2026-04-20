"""Integration tests for the PageRank centrality boost inside the pipeline."""

from __future__ import annotations

from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph
from libs.retrieval.pipeline import _apply_centrality_boost


def _rel(src: str, dst: str) -> Relation:
    return Relation(
        src_type="file",
        src_ref=src,
        dst_type="file",
        dst_ref=dst,
        relation_type=RelationType.IMPORTS,
    )


class TestApplyCentralityBoost:
    def test_no_candidates_is_noop(self) -> None:
        scores: dict[str, float] = {}
        g = Graph()
        g.add_relation(_rel("a.py", "b.py"))
        _apply_centrality_boost(scores, g)
        assert scores == {}

    def test_empty_graph_is_noop(self) -> None:
        scores = {"a.py": 1.0, "b.py": 2.0}
        before = dict(scores)
        _apply_centrality_boost(scores, Graph())
        assert scores == before

    def test_above_median_file_is_boosted(self) -> None:
        # Hub file is imported by three siblings.
        g = Graph()
        g.add_relations(
            [
                _rel("a.py", "hub.py"),
                _rel("b.py", "hub.py"),
                _rel("c.py", "hub.py"),
            ]
        )
        scores = {"a.py": 1.0, "b.py": 1.0, "c.py": 1.0, "hub.py": 1.0}
        _apply_centrality_boost(scores, g)

        # Hub is boosted; leaves stay put because they're at or below the median.
        assert scores["hub.py"] > 1.0
        assert scores["a.py"] == 1.0
        assert scores["b.py"] == 1.0

    def test_boost_never_exceeds_configured_max(self) -> None:
        from libs.retrieval.pipeline import CENTRALITY_BOOST_MAX

        g = Graph()
        g.add_relations(
            [
                _rel("a.py", "hub.py"),
                _rel("b.py", "hub.py"),
                _rel("c.py", "hub.py"),
                _rel("d.py", "hub.py"),
            ]
        )
        scores = {"a.py": 1.0, "b.py": 1.0, "c.py": 1.0, "d.py": 1.0, "hub.py": 1.0}
        _apply_centrality_boost(scores, g)
        for score in scores.values():
            assert score <= 1.0 * CENTRALITY_BOOST_MAX + 1e-9

    def test_two_candidates_still_boost_higher(self) -> None:
        # Regression: before the lower-median fix, a 2-file candidate set
        # always collapsed to `max_val <= mid` and no boost fired.
        g = Graph()
        g.add_relations(
            [
                _rel("a.py", "hub.py"),
                _rel("b.py", "hub.py"),
                _rel("c.py", "hub.py"),
            ]
        )
        scores = {"a.py": 1.0, "hub.py": 1.0}
        _apply_centrality_boost(scores, g)
        assert scores["hub.py"] > scores["a.py"]

    def test_file_not_in_graph_is_unaffected(self) -> None:
        g = Graph()
        g.add_relations(
            [
                _rel("a.py", "hub.py"),
                _rel("b.py", "hub.py"),
            ]
        )
        scores = {"hub.py": 1.0, "orphan.py": 1.0, "a.py": 1.0, "b.py": 1.0}
        _apply_centrality_boost(scores, g)
        # Orphan not in the relation graph keeps its score (centrality 0).
        assert scores["orphan.py"] == 1.0
