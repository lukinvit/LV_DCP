from pathlib import Path

from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_pack_after_scan(sample_repo_path: Path) -> None:
    scan_result = runner.invoke(app, ["scan", str(sample_repo_path)])
    assert scan_result.exit_code == 0

    pack_result = runner.invoke(
        app,
        ["pack", str(sample_repo_path), "login endpoint", "--mode", "navigate"],
    )
    assert pack_result.exit_code == 0, pack_result.output
    assert "app/handlers/auth.py" in pack_result.output


def test_pack_edit_mode(sample_repo_path: Path) -> None:
    runner.invoke(app, ["scan", str(sample_repo_path)])
    result = runner.invoke(
        app,
        ["pack", str(sample_repo_path), "change login validation", "--mode", "edit"],
    )
    assert result.exit_code == 0
    assert "Target files" in result.output or "target" in result.output.lower()


def test_pack_exits_with_error_when_cache_missing(tmp_path: Path) -> None:
    """ctx pack on a never-scanned directory must fail cleanly."""
    (tmp_path / "hello.py").write_text("def hi():\n    pass\n")
    result = runner.invoke(app, ["pack", str(tmp_path), "hello"])
    assert result.exit_code != 0
    # Error message should tell the user to run scan first
    combined = result.output + (result.stderr or "")
    assert "scan" in combined.lower()
