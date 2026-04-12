"""Tests for graph clustering by module directory."""

from __future__ import annotations

from libs.status.aggregator import _cluster_files
from libs.status.models import GraphEdge, GraphNode


def _make_nodes_and_edges() -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes = [
        GraphNode(id="libs/retrieval/pipeline.py", label="pipeline.py", role="code"),
        GraphNode(id="libs/retrieval/fts.py", label="fts.py", role="code"),
        GraphNode(id="libs/retrieval/stemmer.py", label="stemmer.py", role="code"),
        GraphNode(id="libs/graph/builder.py", label="builder.py", role="code"),
        GraphNode(id="apps/ui/main.py", label="main.py", role="code"),
        GraphNode(id="apps/ui/routes/api.py", label="api.py", role="code"),
        GraphNode(id="tests/unit/test_fts.py", label="test_fts.py", role="test"),
        GraphNode(id="tests/unit/test_pipe.py", label="test_pipe.py", role="test"),
        GraphNode(id="docs/readme.md", label="readme.md", role="docs"),
    ]
    edges = [
        GraphEdge(src="libs/retrieval/pipeline.py", dst="libs/retrieval/fts.py"),
        GraphEdge(src="libs/retrieval/pipeline.py", dst="libs/retrieval/stemmer.py"),
        GraphEdge(src="libs/retrieval/pipeline.py", dst="libs/graph/builder.py"),
        GraphEdge(src="apps/ui/routes/api.py", dst="apps/ui/main.py"),
        GraphEdge(src="tests/unit/test_fts.py", dst="libs/retrieval/fts.py"),
        GraphEdge(src="tests/unit/test_pipe.py", dst="libs/retrieval/pipeline.py"),
    ]
    return nodes, edges


class TestClusterFiles:
    def test_groups_by_top2_directory(self) -> None:
        nodes, edges = _make_nodes_and_edges()
        clusters = _cluster_files(nodes, edges, max_clusters=50, files_per_cluster=20)
        cluster_ids = {c.id for c in clusters}
        assert "libs/retrieval" in cluster_ids
        assert "libs/graph" in cluster_ids
        assert "apps/ui" in cluster_ids
        assert "tests/unit" in cluster_ids

    def test_clusters_sorted_by_total_degree(self) -> None:
        nodes, edges = _make_nodes_and_edges()
        clusters = _cluster_files(nodes, edges, max_clusters=50, files_per_cluster=20)
        degrees = [c.total_degree for c in clusters]
        assert degrees == sorted(degrees, reverse=True)

    def test_files_in_cluster_sorted_by_degree(self) -> None:
        nodes, edges = _make_nodes_and_edges()
        clusters = _cluster_files(nodes, edges, max_clusters=50, files_per_cluster=20)
        retrieval = next(c for c in clusters if c.id == "libs/retrieval")
        file_degrees = [f.degree for f in retrieval.top_files]
        assert file_degrees == sorted(file_degrees, reverse=True)

    def test_max_clusters_limit(self) -> None:
        nodes, edges = _make_nodes_and_edges()
        clusters = _cluster_files(nodes, edges, max_clusters=2, files_per_cluster=20)
        assert len(clusters) <= 2

    def test_files_per_cluster_limit(self) -> None:
        nodes, edges = _make_nodes_and_edges()
        clusters = _cluster_files(nodes, edges, max_clusters=50, files_per_cluster=2)
        for c in clusters:
            assert len(c.top_files) <= 2

    def test_root_level_files_cluster(self) -> None:
        nodes = [GraphNode(id="setup.py", label="setup.py", role="config")]
        clusters = _cluster_files(nodes, [], max_clusters=50, files_per_cluster=20)
        assert len(clusters) == 1
        assert clusters[0].id == "."

    def test_inter_cluster_edges(self) -> None:
        nodes, edges = _make_nodes_and_edges()
        clusters = _cluster_files(nodes, edges, max_clusters=50, files_per_cluster=20)
        retrieval = next(c for c in clusters if c.id == "libs/retrieval")
        assert retrieval.inter_cluster_edges > 0
