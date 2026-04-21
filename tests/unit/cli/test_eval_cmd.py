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
        ["eval", "run", str(indexed_project), "--queries", str(queries_file)],
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
            "run",
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
        ["eval", "run", str(plain), "--queries", str(queries_file)],
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
            "run",
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
            "run",
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


def test_eval_run_save_to_persists_snapshot(
    indexed_project: Path, queries_file: Path, tmp_path: Path
) -> None:
    save_dir = tmp_path / "runs"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--save-to",
            str(save_dir),
        ],
    )
    assert result.exit_code == 0, result.stdout
    snapshots = list(save_dir.glob("*.json"))
    assert len(snapshots) == 1
    assert "saved snapshot:" in result.stdout


def test_eval_history_reports_no_runs(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["eval", "history", "--dir", str(empty)])
    assert result.exit_code == 0, result.stdout
    assert "no eval runs" in result.stdout


def test_eval_history_lists_saved_runs(
    indexed_project: Path, queries_file: Path, tmp_path: Path
) -> None:
    save_dir = tmp_path / "runs"
    runner = CliRunner()
    # First save a run so there's something to list.
    save_result = runner.invoke(
        app,
        [
            "eval",
            "run",
            str(indexed_project),
            "--queries",
            str(queries_file),
            "--save-to",
            str(save_dir),
        ],
    )
    assert save_result.exit_code == 0, save_result.stdout

    history_result = runner.invoke(
        app, ["eval", "history", "--dir", str(save_dir), "--limit", "5"]
    )
    assert history_result.exit_code == 0, history_result.stdout
    assert "| run |" in history_result.stdout
    assert ".json" in history_result.stdout


def test_eval_compare_diffs_two_snapshots(
    indexed_project: Path, queries_file: Path, tmp_path: Path
) -> None:
    save_dir = tmp_path / "runs"
    runner = CliRunner()
    for name in ("a", "b"):
        result = runner.invoke(
            app,
            [
                "eval",
                "run",
                str(indexed_project),
                "--queries",
                str(queries_file),
                "--save-to",
                str(save_dir),
            ],
        )
        assert result.exit_code == 0, result.stdout
        # Rename the latest snapshot to a predictable path.
        latest = max(save_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        latest.rename(save_dir / f"{name}.json")

    compare_result = runner.invoke(
        app,
        [
            "eval",
            "compare",
            str(save_dir / "a.json"),
            str(save_dir / "b.json"),
        ],
    )
    assert compare_result.exit_code == 0, compare_result.stdout
    out = compare_result.stdout
    assert "| metric | a | b | delta |" in out
    assert "recall_at_5_files" in out
