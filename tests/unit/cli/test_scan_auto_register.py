"""Test that ctx scan auto-registers projects in config.yaml."""

from __future__ import annotations

from pathlib import Path

from apps.cli.commands.scan import _auto_register


def test_auto_register_adds_to_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: 1\nprojects: []\n")
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    (project_root / "main.py").write_text("print('hello')")
    (project_root / "pyproject.toml").write_text("[project]\nname='test'\n")

    _auto_register(config_path, project_root)

    from libs.core.projects_config import load_config

    cfg = load_config(config_path)
    assert len(cfg.projects) == 1
    assert cfg.projects[0].root == project_root


def test_auto_register_idempotent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: 1\nprojects: []\n")
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    (project_root / ".git").mkdir()  # project marker

    _auto_register(config_path, project_root)
    _auto_register(config_path, project_root)

    from libs.core.projects_config import load_config

    cfg = load_config(config_path)
    assert len(cfg.projects) == 1


def test_auto_register_skips_worktree_paths(tmp_path: Path) -> None:
    """Regression guard for v0.8.35: ``ctx scan`` running inside a
    ship-ceremony worktree (``.claude/worktrees/<branch>/``) must NOT
    auto-register the worktree into the user's real ``~/.lvdcp/config.yaml``.
    The worktree disappears the moment it is cleaned up; registering it
    just accumulates audit noise that ``ctx registry prune`` then has to
    chase down.
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: 1\nprojects: []\n")
    worktree = tmp_path / ".claude" / "worktrees" / "v0.8.35-abc"
    worktree.mkdir(parents=True)
    (worktree / ".git").mkdir()  # marker present
    (worktree / "pyproject.toml").write_text("[project]\nname='wt'\n")

    _auto_register(config_path, worktree)

    from libs.core.projects_config import load_config

    cfg = load_config(config_path)
    assert cfg.projects == []
