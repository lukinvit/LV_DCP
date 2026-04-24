"""Integration tests: /project/<slug> renders the wiki_refresh panel.

Covers the four shapes the partial must support:

1. no data at all          → panel not rendered
2. last refresh was clean  → green "Last refresh: clean" card
3. last refresh crashed    → red FAILED card with log-tail <details>
4. refresh in progress     → blue "Running" card with phase + progress
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest
import yaml
from apps.agent.config import add_project
from apps.ui.main import create_app
from libs.copilot.wiki_background import write_last_refresh
from libs.scanning.scanner import scan_project


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"version": 1, "projects": []}))
    add_project(cfg, project)
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))


def _seed_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    scan_project(project, mode="full")
    _env(tmp_path, monkeypatch, project)
    return project


def _slug(project: Path) -> str:
    return project.name.lower().replace("_", "-")


@pytest.mark.asyncio
async def test_project_detail_hides_panel_when_no_refresh_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh project with no lock and no .refresh.last → no panel at all."""
    project = _seed_project(tmp_path, monkeypatch)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # Panel header must be absent — partial short-circuits on `wr is None`
    # or when both in_progress=False and last_exit_code is None.
    assert "Wiki background refresh" not in response.text


@pytest.mark.asyncio
async def test_project_detail_renders_clean_last_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit_code=0 last run → green 'Last refresh: clean' card, no log tail."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=0,
        modules_updated=7,
        elapsed_seconds=4.2,
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Wiki background refresh" in response.text
    assert "Last refresh: clean" in response.text
    assert "7 modules updated" in response.text
    # Clean run must NOT surface a log tail control.
    assert "Log tail" not in response.text


@pytest.mark.asyncio
async def test_project_detail_renders_crash_with_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exit_code=1 last run with log_tail → red FAILED card + <details> block."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(
        project,
        exit_code=1,
        modules_updated=3,
        elapsed_seconds=12.0,
        log_tail=[
            "ERROR: llm provider timed out",
            "Traceback (most recent call last):",
            "RuntimeError: upstream 504",
        ],
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Wiki background refresh" in response.text
    assert "FAILED (exit 1)" in response.text
    assert "3 modules updated before crash" in response.text
    # Log tail lines must be rendered inside the collapsible block.
    assert "Log tail" in response.text
    assert "llm provider timed out" in response.text
    assert "RuntimeError: upstream 504" in response.text


@pytest.mark.asyncio
async def test_project_detail_renders_live_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live lock with our own PID → blue 'Running' card with phase and progress."""
    project = _seed_project(tmp_path, monkeypatch)
    lock_dir = project / ".context" / "wiki"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = lock_dir / ".refresh.lock"
    # Use the test process's own PID so `_pid_alive` returns True without
    # having to monkeypatch anything.
    lock.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.time(),
                "phase": "generating",
                "modules_total": 5,
                "modules_done": 2,
                "current_module": "libs/foo",
            }
        )
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert "Wiki background refresh" in response.text
    assert "Running" in response.text
    assert "phase: generating" in response.text
    assert "2 / 5 modules" in response.text
    assert "libs/foo" in response.text
