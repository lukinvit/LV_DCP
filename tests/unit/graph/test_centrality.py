"""Tests for PageRank-style centrality on the symbol/file graph."""

from __future__ import annotations

import math

from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph
from libs.graph.centrality import pagerank


def _rel(src: str, dst: str) -> Relation:
    return Relation(
        src_type="symbol",
        src_ref=src,
        dst_type="symbol",
        dst_ref=dst,
        relation_type=RelationType.SAME_FILE_CALLS,
    )


class TestPagerankBasics:
    def test_empty_graph_returns_empty_dict(self) -> None:
        assert pagerank(Graph()) == {}

    def test_single_node_gets_full_mass(self) -> None:
        g = Graph()
        g.add_relation(_rel("a", "a"))  # self-loop so node is present
        scores = pagerank(g)
        assert set(scores) == {"a"}
        assert math.isclose(scores["a"], 1.0, abs_tol=1e-6)

    def test_scores_sum_to_one(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c"), _rel("c", "a"), _rel("a", "c")])
        scores = pagerank(g)
        assert math.isclose(sum(scores.values()), 1.0, abs_tol=1e-6)
        assert all(v > 0 for v in scores.values())

    def test_scores_are_nonnegative(self) -> None:
        g = Graph()
        g.add_relations([_rel("x", "y"), _rel("y", "z"), _rel("z", "y")])
        scores = pagerank(g)
        assert all(v >= 0.0 for v in scores.values())


class TestPagerankSemantics:
    def test_widely_referenced_node_beats_leaf(self) -> None:
        # a, b, c, d all point to hub; hub points nowhere.
        g = Graph()
        g.add_relations(
            [
                _rel("a", "hub"),
                _rel("b", "hub"),
                _rel("c", "hub"),
                _rel("d", "hub"),
            ]
        )
        scores = pagerank(g)
        # hub should dominate: it's the sole destination of 4 references.
        for ref in ("a", "b", "c", "d"):
            assert scores["hub"] > scores[ref]

    def test_chain_end_outranks_chain_start(self) -> None:
        # a -> b -> c -> d; d is the most-referenced (transitively).
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c"), _rel("c", "d")])
        scores = pagerank(g)
        assert scores["d"] > scores["a"]

    def test_deterministic_across_runs(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c"), _rel("c", "a"), _rel("d", "a")])
        first = pagerank(g)
        second = pagerank(g)
        assert first == second

    def test_damping_affects_distribution(self) -> None:
        g = Graph()
        g.add_relations(
            [
                _rel("a", "hub"),
                _rel("b", "hub"),
                _rel("c", "hub"),
            ]
        )
        # With full damping the hub should absorb more mass than with low damping.
        high = pagerank(g, damping=0.85)
        low = pagerank(g, damping=0.20)
        assert high["hub"] > low["hub"]


class TestGraphIntegration:
    def test_graph_pagerank_method_caches_result(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c")])
        first = g.pagerank()
        second = g.pagerank()
        # Same dict object — cached.
        assert first is second

    def test_graph_pagerank_cache_invalidates_on_new_relation(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c")])
        before = dict(g.pagerank())
        g.add_relation(_rel("d", "a"))
        after = g.pagerank()
        # Cache was invalidated and recomputed.
        assert "d" in after
        assert after != before


class TestPersonalization:
    def test_personalization_biases_scores(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c"), _rel("c", "a")])
        # No personalization → roughly even.
        uniform = pagerank(g)
        # Heavy personalization toward 'a' should raise its score.
        biased = pagerank(g, personalization={"a": 10.0})
        assert biased["a"] > uniform["a"]

    def test_personalization_empty_falls_back_to_uniform(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "a")])
        uniform = pagerank(g)
        explicit = pagerank(g, personalization={})
        # Empty personalization = uniform teleport.
        for node in uniform:
            assert math.isclose(uniform[node], explicit[node], abs_tol=1e-6)

    def test_personalization_unknown_keys_are_ignored(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "a")])
        scores = pagerank(g, personalization={"nonexistent": 5.0, "a": 1.0})
        # Unknown key contributes nothing; only 'a' gets teleport mass.
        assert scores["a"] > scores["b"]


class TestConvergence:
    def test_converges_within_tolerance(self) -> None:
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c"), _rel("c", "a"), _rel("b", "a")])
        scores = pagerank(g, iterations=200, tolerance=1e-9)
        # Loose sanity: mass preserved, all finite.
        assert math.isclose(sum(scores.values()), 1.0, abs_tol=1e-6)
        assert all(math.isfinite(v) for v in scores.values())

    def test_dangling_node_does_not_lose_mass(self) -> None:
        # c has no outbound; teleport handling should keep sum ≈ 1.
        g = Graph()
        g.add_relations([_rel("a", "b"), _rel("b", "c")])
        scores = pagerank(g)
        assert math.isclose(sum(scores.values()), 1.0, abs_tol=1e-6)
