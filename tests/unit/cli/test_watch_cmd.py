"""Tests for `ctx watch` CLI subgroup (v0.8.35 allow_transient wiring)."""

from __future__ import annotations

from pathlib import Path

import pytest
from apps.cli.main import app
from typer.testing import CliRunner


@pytest.fixture
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect DEFAULT_CONFIG_PATH so tests never touch the real registry."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr("apps.cli.commands.watch_cmd.DEFAULT_CONFIG_PATH", config_path)
    return config_path


def test_watch_add_registers_worktree_path_explicitly(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """`ctx watch add <worktree>` is explicit user intent — the CLI must pass
    ``allow_transient=True`` so the transient filter in ``add_project`` does
    not silently drop the registration. Without this wiring the user would
    type `ctx watch add ./.claude/worktrees/...` and see no entry in
    ``ctx registry ls`` — a confusing silent no-op regression.
    """
    worktree = tmp_path / ".claude" / "worktrees" / "v0.8.35-wt"
    worktree.mkdir(parents=True)

    result = CliRunner().invoke(app, ["watch", "add", str(worktree)])
    assert result.exit_code == 0, result.stdout

    from libs.core.projects_config import load_config

    cfg = load_config(_isolated_config)
    assert len(cfg.projects) == 1
    assert str(cfg.projects[0].root).endswith("v0.8.35-wt")


def test_watch_add_registers_normal_project(
    tmp_path: Path,
    _isolated_config: Path,
) -> None:
    """Baseline: normal paths must still register via `ctx watch add`."""
    project = tmp_path / "MyProject"
    project.mkdir()

    result = CliRunner().invoke(app, ["watch", "add", str(project)])
    assert result.exit_code == 0, result.stdout

    from libs.core.projects_config import load_config

    cfg = load_config(_isolated_config)
    assert len(cfg.projects) == 1
    assert cfg.projects[0].root.name == "MyProject"
