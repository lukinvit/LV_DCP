from pathlib import Path

import pytest
from apps.mcp.tools import (
    NeighborsResult,
    PackResult,
    ScanResultResponse,
    lvdcp_inspect,
    lvdcp_neighbors,
    lvdcp_pack,
    lvdcp_scan,
)
from libs.scanning.scanner import scan_project


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(
        "def login(email: str, password: str) -> None:\n    return None\n"
    )
    scan_project(tmp_path, mode="full")
    return tmp_path


def test_lvdcp_scan_returns_counts(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    result = lvdcp_scan(path=str(tmp_path))
    assert isinstance(result, ScanResultResponse)
    assert result.files >= 1
    assert result.timing_seconds >= 0.0


def test_lvdcp_pack_returns_markdown(indexed_project: Path) -> None:
    result = lvdcp_pack(
        path=str(indexed_project),
        query="login endpoint",
        mode="navigate",
        limit=5,
    )
    assert isinstance(result, PackResult)
    assert "login" in result.markdown.lower()
    assert result.coverage in ("high", "medium", "ambiguous")
    assert "app/auth.py" in result.retrieved_files


def test_lvdcp_pack_on_unindexed_project_raises_structured_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not_indexed"):
        lvdcp_pack(path=str(tmp_path), query="anything", mode="navigate", limit=5)


def test_lvdcp_inspect_returns_stats(indexed_project: Path) -> None:
    result = lvdcp_inspect(path=str(indexed_project))
    assert result.files >= 1
    assert "python" in result.languages


@pytest.fixture
def graph_project(tmp_path: Path) -> Path:
    """A tiny project with two files that import each other for graph tests."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "hub.py").write_text("def compute() -> int:\n    return 42\n")
    (pkg / "edge.py").write_text("from pkg.hub import compute\n\nresult = compute()\n")
    scan_project(tmp_path, mode="full")
    return tmp_path


def test_lvdcp_neighbors_returns_typed_result(graph_project: Path) -> None:
    result = lvdcp_neighbors(path=str(graph_project), node="pkg/hub.py", limit=20)
    assert isinstance(result, NeighborsResult)
    assert result.truncated is False


def test_lvdcp_neighbors_unknown_node_reports_so(graph_project: Path) -> None:
    result = lvdcp_neighbors(path=str(graph_project), node="does/not/exist.py")
    assert result.resolved_kind == "unknown"
    assert result.outgoing == []
    assert result.incoming == []
    assert result.centrality is None


def test_lvdcp_neighbors_on_unindexed_project_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not_indexed"):
        lvdcp_neighbors(path=str(tmp_path), node="anything.py")


def test_lvdcp_neighbors_respects_limit(graph_project: Path) -> None:
    # Tight limit → truncated flag must flip if anything exceeds it.
    result = lvdcp_neighbors(path=str(graph_project), node="pkg/hub.py", limit=0)
    assert result.outgoing == []
    assert result.incoming == []
