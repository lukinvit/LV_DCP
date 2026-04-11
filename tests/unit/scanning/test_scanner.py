from pathlib import Path

import pytest
from libs.scanning.scanner import ScanResult, scan_project


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text('"""app package."""\n')
    (tmp_path / "app" / "main.py").write_text("def entry() -> None:\n    return None\n")
    (tmp_path / "README.md").write_text("# demo\n\n## usage\n")
    return tmp_path


def test_scan_project_full_mode_counts_files(sample_project: Path) -> None:
    result = scan_project(sample_project, mode="full")
    assert isinstance(result, ScanResult)
    assert result.files_scanned == 3
    assert result.symbols_extracted >= 2  # entry + usage heading
    assert result.stale_files_removed == 0


def test_scan_project_returns_elapsed_seconds(sample_project: Path) -> None:
    result = scan_project(sample_project, mode="full")
    assert result.elapsed_seconds >= 0.0


def test_scan_project_incremental_skips_unchanged_files(sample_project: Path) -> None:
    scan_project(sample_project, mode="full")
    result = scan_project(sample_project, mode="incremental")
    # Second incremental run should skip all files (content_hash matches)
    assert result.files_scanned == 3  # still counted, but parsed == 0
    assert result.files_reparsed == 0


def test_scan_project_incremental_reparses_modified(sample_project: Path) -> None:
    scan_project(sample_project, mode="full")
    (sample_project / "app" / "main.py").write_text("def entry() -> int:\n    return 42\n")
    result = scan_project(sample_project, mode="incremental")
    assert result.files_reparsed == 1
