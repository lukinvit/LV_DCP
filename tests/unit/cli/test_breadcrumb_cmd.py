"""Tests for `ctx breadcrumb` command family."""

from __future__ import annotations

from pathlib import Path

from apps.cli.commands.breadcrumb_cmd import app as breadcrumb_app
from typer.testing import CliRunner


def test_capture_writes_breadcrumb(tmp_path: Path, monkeypatch: object) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)  # type: ignore[attr-defined]
    monkeypatch.setattr("apps.cli.commands.breadcrumb_cmd.DEFAULT_STORE_PATH", db)  # type: ignore[attr-defined]
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    r = CliRunner()
    result = r.invoke(breadcrumb_app, ["capture", "--source=hook_stop"])
    assert result.exit_code == 0


def test_list_returns_zero_when_empty(tmp_path: Path, monkeypatch: object) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)  # type: ignore[attr-defined]
    monkeypatch.setattr("apps.cli.commands.breadcrumb_cmd.DEFAULT_STORE_PATH", db)  # type: ignore[attr-defined]
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    r = CliRunner()
    result = r.invoke(breadcrumb_app, ["list"])
    assert result.exit_code == 0


def test_prune_dry_run(tmp_path: Path, monkeypatch: object) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)  # type: ignore[attr-defined]
    monkeypatch.setattr("apps.cli.commands.breadcrumb_cmd.DEFAULT_STORE_PATH", db)  # type: ignore[attr-defined]
    r = CliRunner()
    result = r.invoke(breadcrumb_app, ["prune", "--older-than=14d", "--dry-run"])
    assert result.exit_code == 0
