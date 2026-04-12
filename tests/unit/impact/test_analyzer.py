"""Tests for libs.impact.analyzer — static impact analysis."""

from __future__ import annotations

import pytest
from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph
from libs.impact.analyzer import ImpactReport, analyze_impact


def _chain_relations() -> list[Relation]:
    """a.py DEFINES sym_a, b.py IMPORTS sym_a, b.py DEFINES sym_b, c.py IMPORTS sym_b."""
    return [
        Relation(
            src_type="file",
            src_ref="a.py",
            dst_type="symbol",
            dst_ref="mod.sym_a",
            relation_type=RelationType.DEFINES,
        ),
        Relation(
            src_type="file",
            src_ref="b.py",
            dst_type="symbol",
            dst_ref="mod.sym_a",
            relation_type=RelationType.IMPORTS,
        ),
        Relation(
            src_type="file",
            src_ref="b.py",
            dst_type="symbol",
            dst_ref="mod.sym_b",
            relation_type=RelationType.DEFINES,
        ),
        Relation(
            src_type="file",
            src_ref="c.py",
            dst_type="symbol",
            dst_ref="mod.sym_b",
            relation_type=RelationType.IMPORTS,
        ),
    ]


def _graph_from(rels: list[Relation]) -> Graph:
    g = Graph()
    g.add_relations(rels)
    return g


class TestAnalyzeImpactDirect:
    """Direct dependents discovery."""

    def test_single_direct_dependent(self) -> None:
        rels = _chain_relations()
        g = _graph_from(rels)
        report = analyze_impact("a.py", g, relations=rels)

        assert isinstance(report, ImpactReport)
        assert report.target == "a.py"
        assert "b.py" in report.direct_dependents
        assert "c.py" not in report.direct_dependents

    def test_no_dependents_for_leaf(self) -> None:
        rels = _chain_relations()
        g = _graph_from(rels)
        report = analyze_impact("c.py", g, relations=rels)

        assert report.direct_dependents == []
        assert report.transitive_dependents == []


class TestAnalyzeImpactTransitive:
    """Transitive BFS and depth limit."""

    def test_transitive_chain(self) -> None:
        rels = _chain_relations()
        g = _graph_from(rels)
        report = analyze_impact("a.py", g, relations=rels)

        assert "c.py" in report.transitive_dependents
        # direct dependents should NOT appear in transitive list
        assert "b.py" not in report.transitive_dependents

    def test_max_depth_limits_bfs(self) -> None:
        rels = _chain_relations()
        g = _graph_from(rels)
        report = analyze_impact("a.py", g, relations=rels, max_depth=1)

        # depth=1 means only direct dependents, no transitive
        assert report.direct_dependents == ["b.py"]
        assert report.transitive_dependents == []


class TestAnalyzeImpactTests:
    """Test file detection."""

    def test_affected_tests_detected(self) -> None:
        rels = [
            *_chain_relations(),
            Relation(
                src_type="file",
                src_ref="tests/test_b.py",
                dst_type="symbol",
                dst_ref="mod.sym_b",
                relation_type=RelationType.IMPORTS,
            ),
        ]
        g = _graph_from(rels)
        roles = {"tests/test_b.py": "test"}
        report = analyze_impact("a.py", g, relations=rels, file_roles=roles)

        assert "tests/test_b.py" in report.affected_tests


class TestAnalyzeImpactRisk:
    """Risk score computation."""

    def test_risk_score_with_churn(self) -> None:
        rels = _chain_relations()
        g = _graph_from(rels)
        report = analyze_impact("a.py", g, relations=rels, git_churn=10)

        # fan_in for a.py: files that depend on it = 1 (b.py)
        # fan_out for a.py: files a.py depends on = 0, so max(1, 0) = 1
        # risk = 1 * 1 * (1 + 10/10) = 2.0
        assert report.risk_score == pytest.approx(2.0)

    def test_risk_score_zero_churn(self) -> None:
        rels = _chain_relations()
        g = _graph_from(rels)
        report = analyze_impact("a.py", g, relations=rels, git_churn=0)

        # risk = 1 * 1 * (1 + 0) = 1.0
        assert report.risk_score == pytest.approx(1.0)
