"""Run ctx scan on LV_DCP itself as the single canary project."""

from pathlib import Path

from apps.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_ctx_scan_on_lv_dcp(project_root: Path) -> None:
    # Sanity: this test lives inside LV_DCP, so project_root is the repo itself
    result = runner.invoke(app, ["scan", str(project_root)])
    assert result.exit_code == 0, result.output

    dot = project_root / ".context"
    assert (dot / "project.md").exists()
    assert (dot / "symbol_index.md").exists()

    # Must contain at least some of our own code
    idx = (dot / "symbol_index.md").read_text()
    assert "libs/core" in idx or "libs" in idx
