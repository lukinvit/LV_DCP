"""Tests for the `ctx project` CLI group (spec-011)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from apps.cli.main import app
from libs.scanning.scanner import scan_project
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect both LVDCP_CONFIG_PATH and ``~`` at a tmp dir with Qdrant off.

    Several primitives (scanner, embedder) still hard-code
    ``Path.home() / ".lvdcp" / "config.yaml"`` — overriding ``HOME`` is
    the only way to keep the tests offline.
    """
    home = tmp_path / "home"
    (home / ".lvdcp").mkdir(parents=True)
    cfg = home / ".lvdcp" / "config.yaml"
    cfg.write_text(yaml.safe_dump({"qdrant": {"enabled": False}}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: home))


def _seed_project(root: Path) -> None:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "auth.py").write_text(
        "def login() -> bool:\n    return True\n", encoding="utf-8"
    )


def test_check_on_empty_dir_prints_not_scanned(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "scanned:         False" in result.stdout
    assert "not_scanned" in result.stdout


def test_check_json_flag_parses(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "check", str(proj), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["scanned"] is True
    assert payload["files"] >= 1


def test_refresh_runs_scan_and_skips_wiki_with_flag(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)

    runner = CliRunner()
    result = runner.invoke(app, ["project", "refresh", str(proj), "--no-wiki"])
    assert result.exit_code == 0, result.stdout
    assert "refreshed=False" in result.stdout
    # The scan should have run.
    assert (proj / ".context" / "cache.db").exists()


def test_wiki_subcommand_read_only_without_refresh(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "wiki", str(proj)])
    assert result.exit_code == 0, result.stdout
    assert "wiki present:" in result.stdout


def test_wiki_subcommand_json_shape_is_check_report(tmp_path: Path) -> None:
    """Pin the read-only ``ctx project wiki --json`` contract.

    The read-only path emits a full :class:`CopilotCheckReport`; scripts
    that want a stable schema should call ``ctx project check --json``.
    This test documents the current contract so a future change must
    update it deliberately.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "wiki", str(proj), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # Shape is CopilotCheckReport — must carry these keys.
    for key in (
        "project_root",
        "project_name",
        "scanned",
        "wiki_present",
        "wiki_dirty_modules",
        "qdrant_enabled",
        "degraded_modes",
    ):
        assert key in payload, f"missing check-report key: {key}"
    # And must NOT carry refresh-only keys.
    assert "wiki_refreshed" not in payload
    assert "scan_files" not in payload


def test_ask_rejects_invalid_mode(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "ask", str(proj), "q", "--mode", "bogus"])
    # Rejection is the only contract — `typer.echo(..., err=True)` lands
    # on stderr and the exit code must be 2. The exact message lives on
    # stderr (output varies between CliRunner versions).
    assert result.exit_code == 2


def test_ask_not_scanned_hard_degrade(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["project", "ask", str(proj), "anything"])
    assert result.exit_code == 0, result.stdout
    assert "coverage: unavailable" in result.stdout
    assert "not_scanned" in result.stdout or "not scanned" in result.stdout.lower()


def test_ask_happy_path_prints_pack_and_suggestions(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_project(proj)
    scan_project(proj, mode="full")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "ask", str(proj), "login"])
    assert result.exit_code == 0, result.stdout
    # Pack markdown contains a canonical header.
    assert "Context pack" in result.stdout or "context pack" in result.stdout.lower()
    # Qdrant is off via _isolated_config → we should see the hint.
    assert "trace_id" in result.stdout
