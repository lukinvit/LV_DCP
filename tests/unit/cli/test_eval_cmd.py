"""Tests for the `ctx eval` CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from apps.cli.main import app
from libs.scanning.scanner import scan_project
from typer.testing import CliRunner


@pytest.fixture
def indexed_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(
        "def login(email: str, password: str) -> None:\n    return None\n"
    )
    (tmp_path / "app" / "session.py").write_text("class Session: ...\n")
    scan_project(tmp_path, mode="full")
    return tmp_path


@pytest.fixture
def queries_file(tmp_path: Path) -> Path:
    path = tmp_path / "queries.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "queries": [
                    {
                        "id": "q01",
                        "text": "login endpoint",
                        "mode": "navigate",
                        "expected": {"files": ["app/auth.py"]},
                    },
                    {
                        "id": "q02",
                        "text": "session model",
                        "mode": "navigate",
                        "expected": {"files": ["app/session.py"]},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_eval_cmd_prints_markdown_report(indexed_project: Path, queries_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(indexed_project), "--queries", str(queries_file)],
    )
    assert result.exit_code == 0, result.stdout
    assert "# Eval Report" in result.stdout
    assert "recall@5" in result.stdout
    assert "q01" in result.stdout


def test_eval_cmd_writes_output_file(
    indexed_project: Path, queries_file: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report.md"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    assert "# Eval Report" in out.read_text(encoding="utf-8")


def test_eval_cmd_rejects_unindexed_project(tmp_path: Path, queries_file: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["eval", str(plain), "--queries", str(queries_file)],
    )
    assert result.exit_code == 2
    # typer echoes err=True to stderr; accept either channel.
    stderr = result.stderr or ""
    assert "no cache" in stderr or "no cache" in result.stdout


def test_eval_cmd_rejects_unknown_baseline(indexed_project: Path, queries_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--baseline",
            "cody",
        ],
    )
    assert result.exit_code == 2


def test_eval_cmd_aider_baseline_runs(indexed_project: Path, queries_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--baseline",
            "aider",
        ],
    )
    # Even if the project is tiny, the comparison report should render.
    assert result.exit_code == 0, result.stdout
    assert "Eval Comparison" in result.stdout
    assert "Aider baseline" in result.stdout
