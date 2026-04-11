from pathlib import Path

import pytest
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError
from libs.scanning.scanner import scan_project


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def run() -> None:\n    return None\n")
    scan_project(tmp_path, mode="full")
    return tmp_path


def test_open_existing_project(indexed_project: Path) -> None:
    with ProjectIndex.open(indexed_project) as idx:
        assert idx.root == indexed_project
        assert idx.file_count() >= 1


def test_open_missing_cache_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotIndexedError):
        ProjectIndex.open(tmp_path)


def test_for_scan_creates_missing_cache(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    with ProjectIndex.for_scan(tmp_path) as idx:
        assert idx.root == tmp_path
        # Not auto-scanned — caller must run scanner. But open succeeds.


def test_retrieve_runs_pipeline(indexed_project: Path) -> None:
    with ProjectIndex.open(indexed_project) as idx:
        result = idx.retrieve("run", mode="navigate", limit=5)
        assert "app/main.py" in result.files


def test_public_iter_methods(indexed_project: Path) -> None:
    """iter_files / iter_symbols / iter_relations are exposed as public API."""
    with ProjectIndex.open(indexed_project) as idx:
        files = list(idx.iter_files())
        symbols = list(idx.iter_symbols())
        relations = list(idx.iter_relations())

    assert any(f.path == "app/main.py" for f in files)
    # at least the `run` function should be a symbol
    assert any(s.name == "run" for s in symbols)
    # relations list may be empty for a trivial project — just check type
    assert isinstance(relations, list)


def test_save_and_load_trace(indexed_project: Path) -> None:
    """save_trace / load_trace round-trip through the public API."""
    from libs.retrieval.trace import RetrievalTrace

    trace = RetrievalTrace(
        trace_id="test-trace-1",
        project="test_project",
        query="run",
        mode="navigate",
        timestamp=0.0,
        coverage="high",
    )
    with ProjectIndex.open(indexed_project) as idx:
        idx.save_trace(trace)
        loaded = idx.load_trace("test-trace-1")

    assert loaded is not None
    assert loaded.trace_id == "test-trace-1"
    assert loaded.query == "run"


def test_load_trace_missing_returns_none(indexed_project: Path) -> None:
    with ProjectIndex.open(indexed_project) as idx:
        result = idx.load_trace("no-such-trace")
    assert result is None


def test_delete_file_removes_from_index(indexed_project: Path) -> None:
    """delete_file removes the file from the index without affecting others."""
    # Add a second file and re-scan
    (indexed_project / "app" / "extra.py").write_text("def helper() -> None: pass\n")
    from libs.scanning.scanner import scan_project

    scan_project(indexed_project, mode="full")

    with ProjectIndex.open(indexed_project) as idx:
        before = {f.path for f in idx.iter_files()}
        assert "app/extra.py" in before
        idx.delete_file("app/extra.py")
        after = {f.path for f in idx.iter_files()}

    assert "app/extra.py" not in after
    assert "app/main.py" in after
