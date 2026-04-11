from __future__ import annotations

from pathlib import Path

import pytest
from apps.agent.config import add_project
from libs.scanning.scanner import scan_project
from libs.status.aggregator import build_project_status, build_workspace_status
from libs.status.models import ProjectStatus, WorkspaceStatus


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up an isolated workspace: config.yaml, empty claude_projects, scan_history, usage cache."""
    config = tmp_path / "config.yaml"
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(config))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude_projects"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage_cache.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    return config


def test_build_workspace_status_lists_registered_projects(
    tmp_path: Path, isolated_env: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "main.py").write_text("def main() -> None:\n    return None\n")
    scan_project(project, mode="full")

    add_project(isolated_env, project)

    ws: WorkspaceStatus = build_workspace_status()
    assert ws.projects_count == 1
    assert ws.projects[0].name == "proj"
    assert ws.total_files >= 1


def test_build_workspace_status_empty(isolated_env: Path) -> None:
    ws = build_workspace_status()
    assert ws.projects_count == 0
    assert ws.total_files == 0
    assert ws.projects == []


def test_build_project_status_includes_graph(tmp_path: Path, isolated_env: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("from b import f\n")
    (project / "b.py").write_text("def f() -> None: return None\n")
    scan_project(project, mode="full")

    add_project(isolated_env, project)

    status: ProjectStatus = build_project_status(project.resolve())
    assert status.card.files >= 2
    assert status.graph is not None
    assert len(status.graph.nodes) >= 2


def test_build_project_status_has_four_sparklines(tmp_path: Path, isolated_env: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    add_project(isolated_env, project)

    status = build_project_status(project.resolve())
    metrics = {s.metric for s in status.sparklines}
    assert {"queries", "scans", "latency_p95_ms", "coverage"} == metrics
