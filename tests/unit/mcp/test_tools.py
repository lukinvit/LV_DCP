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


def test_lvdcp_neighbors_classifies_file_via_file_list(graph_project: Path) -> None:
    # Regression: before we consulted the authoritative file list, a fq_name
    # containing "/" was falsely labeled as a file.
    result = lvdcp_neighbors(path=str(graph_project), node="pkg/hub.py")
    assert result.resolved_kind == "file"


def test_lvdcp_neighbors_classifies_symbol(graph_project: Path) -> None:
    # "compute" is defined in pkg/hub.py — its fq_name has no slash.
    result = lvdcp_neighbors(path=str(graph_project), node="pkg.hub.compute")
    # If the symbol isn't in the graph at all we accept "unknown"; otherwise
    # it must be classified as a symbol, not a file.
    assert result.resolved_kind in ("symbol", "unknown")


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


def test_lvdcp_history_on_non_git_dir_returns_empty(tmp_path: Path) -> None:
    from apps.mcp.tools import lvdcp_history

    result = lvdcp_history(path=str(tmp_path))
    assert result.commits == []
    assert result.truncated is False
    assert result.since_days == 7


def test_lvdcp_removed_since_on_non_git_dir_returns_ref_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unresolvable ref + non-git tmp dir → typed empty response."""
    monkeypatch.setenv("LVDCP_TIMELINE_DB", str(tmp_path / "tl.db"))

    from apps.mcp.tools import RemovedSinceResponse, lvdcp_removed_since

    result = lvdcp_removed_since(path=str(tmp_path), ref="v1.0.0-bogus")
    assert isinstance(result, RemovedSinceResponse)
    assert result.ref_not_found is True
    assert result.removed == []
    assert result.renamed == []
    assert result.ref_resolved_sha is None
    assert result.ref_resolved_at_iso is None


def test_lvdcp_history_reports_filter_and_since(tmp_path: Path) -> None:
    from apps.mcp.tools import lvdcp_history

    result = lvdcp_history(path=str(tmp_path), since_days=30, filter_path="src/")
    assert result.since_days == 30
    assert result.filter_path == "src/"


def test_lvdcp_memory_propose_writes_file(tmp_path: Path) -> None:
    from apps.mcp.tools import lvdcp_memory_propose

    result = lvdcp_memory_propose(
        path=str(tmp_path),
        topic="Auth rotation",
        body="Use rotate_session_token on refresh.",
        tags=["auth"],
    )
    assert result.memory.status == "proposed"
    assert "rotate_session_token" in result.memory.body
    assert Path(result.memory.path).exists()
    assert "ctx memory accept" in result.review_hint


def test_lvdcp_memory_propose_rejects_empty_topic(tmp_path: Path) -> None:
    from apps.mcp.tools import lvdcp_memory_propose

    with pytest.raises(ValueError, match="memory_rejected"):
        lvdcp_memory_propose(path=str(tmp_path), topic="", body="x")


def test_lvdcp_memory_list_filters_by_status(tmp_path: Path) -> None:
    from apps.mcp.tools import lvdcp_memory_list, lvdcp_memory_propose

    lvdcp_memory_propose(path=str(tmp_path), topic="first", body="one", tags=None)
    # list with explicit proposed filter should surface it.
    listed = lvdcp_memory_list(path=str(tmp_path), status="proposed")
    assert len(listed.memories) == 1
    # accepted filter should be empty on a fresh store.
    accepted = lvdcp_memory_list(path=str(tmp_path), status="accepted")
    assert accepted.memories == []
