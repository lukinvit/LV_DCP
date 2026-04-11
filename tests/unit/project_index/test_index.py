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
