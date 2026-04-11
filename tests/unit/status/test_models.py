from __future__ import annotations

from libs.status.models import (
    DaemonStatus,
    GraphDump,
    GraphEdge,
    GraphNode,
    HealthCard,
    ProjectStatus,
    SparklineSeries,
    TokenTotals,
    WorkspaceStatus,
)


def test_token_totals_defaults_to_zero() -> None:
    t = TokenTotals()
    assert t.input_tokens == 0
    assert t.output_tokens == 0


def test_token_totals_model_dump() -> None:
    t = TokenTotals(
        input_tokens=1,
        cache_creation_input_tokens=2,
        cache_read_input_tokens=3,
        output_tokens=4,
    )
    data = t.model_dump()
    assert data == {
        "input_tokens": 1,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 3,
        "output_tokens": 4,
    }


def test_workspace_status_serializes() -> None:
    ws = WorkspaceStatus(
        projects_count=2,
        total_files=100,
        total_symbols=500,
        total_relations=1000,
        daemon=DaemonStatus(state="running", detail=""),
        claude_usage_7d=TokenTotals(
            input_tokens=10,
            cache_creation_input_tokens=20,
            cache_read_input_tokens=30,
            output_tokens=40,
        ),
        claude_usage_30d=TokenTotals(),
        projects=[],
    )
    data = ws.model_dump()
    assert data["projects_count"] == 2
    assert data["daemon"]["state"] == "running"
    assert data["claude_usage_7d"]["input_tokens"] == 10


def test_project_status_with_graph() -> None:
    card = HealthCard(
        root="/x",
        name="x",
        slug="x",
        files=1,
        symbols=2,
        relations=3,
    )
    graph = GraphDump(
        nodes=[GraphNode(id="a.py", label="a.py", role="code")],
        edges=[],
    )
    ps = ProjectStatus(
        card=card,
        claude_usage_7d=TokenTotals(),
        claude_usage_30d=TokenTotals(),
        sparklines=[SparklineSeries(metric="queries", window="7d")],
        graph=graph,
    )
    data = ps.model_dump()
    assert data["card"]["name"] == "x"
    assert len(data["graph"]["nodes"]) == 1
    assert data["sparklines"][0]["metric"] == "queries"


def test_graph_edge_roundtrip() -> None:
    e = GraphEdge(src="a", dst="b")
    assert e.model_dump() == {"src": "a", "dst": "b"}
