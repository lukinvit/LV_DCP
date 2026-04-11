from pathlib import Path

from apps.agent.config import (
    DaemonConfig,
    ProjectEntry,
    add_project,
    list_projects,
    load_config,
    remove_project,
    save_config,
)


def test_config_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    cfg = DaemonConfig(
        version=1,
        projects=[
            ProjectEntry(root=Path("/abs/project-a"), registered_at_iso="2026-04-11T09:30:00Z"),
        ],
    )
    save_config(config_path, cfg)

    loaded = load_config(config_path)
    assert loaded.version == 1
    assert len(loaded.projects) == 1
    assert loaded.projects[0].root == Path("/abs/project-a")


def test_load_missing_config_returns_empty(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yaml"
    cfg = load_config(config_path)
    assert cfg.version == 1
    assert cfg.projects == []


def test_add_project_is_idempotent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    add_project(config_path, Path("/abs/a"))
    add_project(config_path, Path("/abs/a"))
    projects = list_projects(config_path)
    assert len(projects) == 1


def test_add_project_multiple(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    add_project(config_path, Path("/abs/a"))
    add_project(config_path, Path("/abs/b"))
    projects = list_projects(config_path)
    assert len(projects) == 2


def test_remove_project(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    add_project(config_path, Path("/abs/a"))
    add_project(config_path, Path("/abs/b"))
    remove_project(config_path, Path("/abs/a"))
    projects = list_projects(config_path)
    assert len(projects) == 1
    assert projects[0].root == Path("/abs/b")


def test_remove_missing_project_no_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    remove_project(config_path, Path("/abs/nonexistent"))  # should not raise
