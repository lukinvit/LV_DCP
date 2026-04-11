from pathlib import Path

import pytest
from apps.mcp.tools import (
    PackResult,
    ScanResultResponse,
    lvdcp_inspect,
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
