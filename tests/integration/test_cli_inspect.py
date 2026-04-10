from pathlib import Path

from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_inspect_reports_stats(sample_repo_path: Path) -> None:
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(app, ["inspect", str(sample_repo_path)])
    assert result.exit_code == 0
    assert "files" in result.output.lower()
    assert "symbols" in result.output.lower()
    assert "relations" in result.output.lower()
