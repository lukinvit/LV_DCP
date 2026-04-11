from pathlib import Path

from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_scan_fixture_repo(sample_repo_path: Path, tmp_path: Path) -> None:
    # Copy-free: scan in-place, write artifacts to .context/ under sample_repo
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0, result.output
    assert (sample_repo_path / ".context" / "project.md").exists()
    assert (sample_repo_path / ".context" / "symbol_index.md").exists()

    index_content = (sample_repo_path / ".context" / "symbol_index.md").read_text()
    assert "User" in index_content
    assert "login" in index_content


def test_scan_reports_counts(sample_repo_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0
    assert "files" in result.output.lower()
    assert "symbols" in result.output.lower()


def test_scan_populates_fts_index(sample_repo_path: Path) -> None:
    """After ctx scan, the FTS index at .context/fts.db must be populated."""
    result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert result.exit_code == 0
    fts_path = sample_repo_path / ".context" / "fts.db"
    assert fts_path.exists()

    from libs.retrieval.fts import FtsIndex

    fts = FtsIndex(fts_path)
    fts.create()
    # Must find content from our known fixture
    results = fts.search("refresh token", limit=5)
    assert any("auth" in path.lower() for path, _score in results)
