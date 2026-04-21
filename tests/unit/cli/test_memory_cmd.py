"""Tests for the `ctx memory` CLI group."""

from __future__ import annotations

from pathlib import Path

import pytest
from apps.cli.main import app
from libs.memory.store import propose_memory
from typer.testing import CliRunner


@pytest.fixture
def project_with_memory(tmp_path: Path) -> tuple[Path, str]:
    m = propose_memory(tmp_path, topic="Auth flow", body="JWT rotation notes.")
    return tmp_path, m.id


def test_memory_list_shows_proposed(project_with_memory: tuple[Path, str]) -> None:
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "list", "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert mem_id in result.stdout
    assert "proposed" in result.stdout


def test_memory_list_status_filter(project_with_memory: tuple[Path, str]) -> None:
    project, _ = project_with_memory
    runner = CliRunner()
    accepted = runner.invoke(
        app, ["memory", "list", "--project", str(project), "--status", "accepted"]
    )
    assert accepted.exit_code == 0
    # No accepted memories yet — listing must say so.
    assert "(no memories)" in accepted.stdout


def test_memory_accept_flips_status(project_with_memory: tuple[Path, str]) -> None:
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "accept", mem_id, "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert "accepted" in result.stdout.lower()
    # Verify via list filter.
    listed = runner.invoke(
        app, ["memory", "list", "--project", str(project), "--status", "accepted"]
    )
    assert mem_id in listed.stdout


def test_memory_reject_flips_status(project_with_memory: tuple[Path, str]) -> None:
    project, mem_id = project_with_memory
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "reject", mem_id, "--project", str(project)])
    assert result.exit_code == 0, result.stdout
    assert "rejected" in result.stdout.lower()


def test_memory_accept_unknown_id_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["memory", "accept", "mem_unknown_id", "--project", str(tmp_path)],
    )
    assert result.exit_code == 2
