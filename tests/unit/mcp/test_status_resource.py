from __future__ import annotations

from pathlib import Path

import pytest
from apps.agent.config import add_project
from apps.mcp.tools import lvdcp_status
from libs.scanning.scanner import scan_project


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config.yaml"
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(config))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    return config


def test_lvdcp_status_without_path_returns_workspace(
    tmp_path: Path, isolated_env: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n")
    scan_project(project, mode="full")
    add_project(isolated_env, project)

    result = lvdcp_status()
    assert result.workspace is not None
    assert result.workspace.projects_count == 1
    assert result.project is None


def test_lvdcp_status_with_path_returns_project(
    tmp_path: Path, isolated_env: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("def f() -> None: return None\n")
    scan_project(project, mode="full")
    add_project(isolated_env, project)

    result = lvdcp_status(path=str(project))
    assert result.workspace is None
    assert result.project is not None
    assert result.project.card.files >= 1
    assert result.project.graph is not None
