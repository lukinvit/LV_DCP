from datetime import UTC, datetime
from pathlib import Path

import apps.agent.config as agent_config
import libs.core.projects_config as core_config
from apps.agent.config import (
    DaemonConfig,
    ProjectEntry,
    add_project,
    list_projects,
    load_config,
    remove_project,
    save_config,
    update_last_scan,
)


def test_save_config_is_single_source_of_truth() -> None:
    """apps.agent.config.save_config must delegate to the atomic libs version.

    Regression guard for v0.8.34 — prevents a future refactor from
    reintroducing a second, non-atomic `save_config` that would silently
    skip fsync/rename and corrupt the registry on crash.
    """
    assert agent_config.save_config is core_config.save_config


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


def test_update_last_scan_writes_iso_timestamp(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    project_root = tmp_path / "proj"
    project_root.mkdir()

    add_project(config_path, project_root)
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    update_last_scan(config_path, project_root, status="ok", ts_iso=ts)

    projects = list_projects(config_path)
    assert len(projects) == 1
    entry = projects[0]
    assert entry.last_scan_at_iso == ts
    assert entry.last_scan_status == "ok"


def test_update_last_scan_noop_for_unknown_project(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    project_root = tmp_path / "proj"

    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    update_last_scan(config_path, project_root, status="ok", ts_iso=ts)

    projects = list_projects(config_path)
    assert projects == []
