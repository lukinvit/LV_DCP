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


# ---- v0.8.35: transient path filter on auto-registration -----------------


def test_add_project_skips_worktree_paths_by_default(tmp_path: Path) -> None:
    """Implicit auto-register (e.g. `ctx scan` inside a ship worktree) must
    not grow the registry with paths that vanish as soon as the worktree is
    removed. The classifier lives in ``libs.core.projects_config.is_transient``.
    """
    config_path = tmp_path / "config.yaml"
    worktree = tmp_path / ".claude" / "worktrees" / "v0.8.35-abc"
    worktree.mkdir(parents=True)

    add_project(config_path, worktree)  # allow_transient defaults to False

    assert list_projects(config_path) == []


def test_add_project_skips_sample_repo_fixture(tmp_path: Path) -> None:
    """The shared pytest ``sample_repo`` fixture must not accumulate in the
    user's real registry when unit tests happen to auto-register it.
    """
    config_path = tmp_path / "config.yaml"
    fixture = tmp_path / "tests" / "fixtures" / "sample_repo"
    fixture.mkdir(parents=True)

    add_project(config_path, fixture)

    assert list_projects(config_path) == []


def test_add_project_registers_transient_when_explicit(tmp_path: Path) -> None:
    """``ctx watch add`` is explicit user intent — it passes
    ``allow_transient=True`` so the user can legitimately target a worktree
    or fixture if they really want to.
    """
    config_path = tmp_path / "config.yaml"
    worktree = tmp_path / ".claude" / "worktrees" / "v0.8.35-abc"
    worktree.mkdir(parents=True)

    add_project(config_path, worktree, allow_transient=True)

    projects = list_projects(config_path)
    assert len(projects) == 1
    assert str(projects[0].root).endswith("v0.8.35-abc")


def test_add_project_registers_real_project_without_flag(tmp_path: Path) -> None:
    """Regression guard: the transient filter must not reject normal paths."""
    config_path = tmp_path / "config.yaml"
    real = tmp_path / "Nextcloud" / "projects" / "MyApp"
    real.mkdir(parents=True)

    add_project(config_path, real)

    projects = list_projects(config_path)
    assert len(projects) == 1
    assert str(projects[0].root).endswith("MyApp")
