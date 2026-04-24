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


# ---- wiki_refresh surface (v0.8.6) ----------------------------------------


def _seed_scan(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "main.py").write_text("def f() -> None: return None\n", encoding="utf-8")
    scan_project(project, mode="full")


def test_build_project_status_wiki_refresh_idle_with_no_history(
    tmp_path: Path, isolated_env: Path
) -> None:
    """Fresh project, no refresh ever run → all fields are default/empty."""
    project = tmp_path / "proj"
    _seed_scan(project)
    add_project(isolated_env, project)

    status = build_project_status(project.resolve())
    assert status.wiki_refresh is not None
    wr = status.wiki_refresh
    assert wr.in_progress is False
    assert wr.phase is None
    assert wr.modules_total is None
    assert wr.modules_done == 0
    assert wr.pid is None
    assert wr.last_completed_at is None
    assert wr.last_exit_code is None
    assert wr.last_log_tail is None


def test_build_project_status_wiki_refresh_surfaces_last_crash(
    tmp_path: Path, isolated_env: Path
) -> None:
    """A crashed refresh populates ``last_*`` including the log tail."""
    from libs.copilot import write_last_refresh

    project = tmp_path / "proj"
    _seed_scan(project)
    add_project(isolated_env, project)
    (project / ".context" / "wiki").mkdir(parents=True, exist_ok=True)

    tail = [
        "Traceback (most recent call last):",
        '  File "x.py", line 10, in _run',
        "RuntimeError: boom",
    ]
    write_last_refresh(
        project,
        exit_code=1,
        modules_updated=2,
        elapsed_seconds=0.5,
        completed_at=1_700_000_000.0,
        log_tail=tail,
    )

    status = build_project_status(project.resolve())
    assert status.wiki_refresh is not None
    wr = status.wiki_refresh
    assert wr.in_progress is False
    assert wr.last_exit_code == 1
    assert wr.last_modules_updated == 2
    assert wr.last_elapsed_seconds == pytest.approx(0.5)
    assert wr.last_completed_at == pytest.approx(1_700_000_000.0)
    assert wr.last_log_tail == tail


def test_build_project_status_wiki_refresh_shows_live_progress(
    tmp_path: Path, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live lock with progress payload populates the ``in_progress`` block."""
    import json as _json
    import time as _time

    project = tmp_path / "proj"
    _seed_scan(project)
    add_project(isolated_env, project)

    wiki_dir = project / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / ".refresh.lock").write_text(
        _json.dumps(
            {
                "pid": 42424,
                "started_at": _time.time(),
                "all_modules": False,
                "phase": "generating",
                "modules_total": 5,
                "modules_done": 2,
                "current_module": "libs/foo",
            }
        ),
        encoding="utf-8",
    )
    from libs.copilot import wiki_background

    monkeypatch.setattr(wiki_background, "_pid_alive", lambda _pid: True)

    status = build_project_status(project.resolve())
    assert status.wiki_refresh is not None
    wr = status.wiki_refresh
    assert wr.in_progress is True
    assert wr.phase == "generating"
    assert wr.modules_total == 5
    assert wr.modules_done == 2
    assert wr.current_module == "libs/foo"
    assert wr.pid == 42424


def test_build_project_status_wiki_refresh_clean_last_run_has_no_log_tail(
    tmp_path: Path, isolated_env: Path
) -> None:
    """Clean runs intentionally leave ``last_log_tail`` empty."""
    from libs.copilot import write_last_refresh

    project = tmp_path / "proj"
    _seed_scan(project)
    add_project(isolated_env, project)
    (project / ".context" / "wiki").mkdir(parents=True, exist_ok=True)
    write_last_refresh(
        project,
        exit_code=0,
        modules_updated=3,
        elapsed_seconds=2.0,
        completed_at=1_700_000_000.0,
    )

    status = build_project_status(project.resolve())
    assert status.wiki_refresh is not None
    assert status.wiki_refresh.last_exit_code == 0
    assert status.wiki_refresh.last_log_tail is None
