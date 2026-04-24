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


def _seed_running_lock(project: Path, *, phase: str = "generating") -> None:
    """Write a `.refresh.lock` pointing at the test process so _pid_alive=True."""
    lock_dir = project / ".context" / "wiki"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / ".refresh.lock").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": time.time(),
                "phase": phase,
                "modules_total": 5,
                "modules_done": 2,
                "current_module": "libs/foo",
            }
        )
    )


@pytest.mark.asyncio
async def test_project_detail_renders_live_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live lock with our own PID → blue 'Running' card with phase and progress."""
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

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


# -------- v0.8.8: HTMX polling fragment -----------------------------


@pytest.mark.asyncio
async def test_project_detail_adds_htmx_polling_while_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full page render while running must emit hx-get + hx-trigger on the wrapper."""
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    # The wrapper must carry the polling attributes so HTMX starts its
    # timer on page load — the whole point of v0.8.8.
    assert f'hx-get="/api/project/{_slug(project)}/wiki-refresh"' in response.text
    assert 'hx-trigger="every 2s"' in response.text
    assert 'hx-swap="outerHTML"' in response.text
    assert 'id="wiki-refresh-panel"' in response.text


@pytest.mark.asyncio
async def test_project_detail_omits_htmx_polling_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No running refresh → wrapper has NO hx-get, so HTMX stays silent."""
    project = _seed_project(tmp_path, monkeypatch)
    # Seed a clean last-run record so the section renders — we want to
    # verify the wrapper is present but without polling attributes.
    write_last_refresh(project, exit_code=0, modules_updated=3, elapsed_seconds=2.5)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{_slug(project)}")

    assert response.status_code == 200
    assert 'id="wiki-refresh-panel"' in response.text
    # Slice to just the wrapper's opening tag to be sure no hx-get on it.
    panel_slice = response.text.split('id="wiki-refresh-panel"', 1)[1].split(">", 1)[0]
    assert "hx-get=" not in panel_slice
    assert "Last refresh: clean" in response.text


@pytest.mark.asyncio
async def test_wiki_refresh_fragment_endpoint_returns_running_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/project/<slug>/wiki-refresh during a refresh returns running HTML + polling."""
    project = _seed_project(tmp_path, monkeypatch)
    _seed_running_lock(project)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/project/{_slug(project)}/wiki-refresh")

    assert response.status_code == 200
    # Fragment must include the wrapper + hx-get so HTMX keeps polling.
    assert 'id="wiki-refresh-panel"' in response.text
    assert f'hx-get="/api/project/{_slug(project)}/wiki-refresh"' in response.text
    assert "Running" in response.text
    assert "phase: generating" in response.text
    # Fragment must NOT be a full HTML page — no <html>/<body>/<header>.
    assert "<html" not in response.text
    assert "<body" not in response.text


@pytest.mark.asyncio
async def test_wiki_refresh_fragment_endpoint_stops_polling_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the refresh completes, the fragment response has NO hx-get → polling halts."""
    project = _seed_project(tmp_path, monkeypatch)
    write_last_refresh(project, exit_code=0, modules_updated=7, elapsed_seconds=4.2)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/project/{_slug(project)}/wiki-refresh")

    assert response.status_code == 200
    assert 'id="wiki-refresh-panel"' in response.text
    assert "hx-get=" not in response.text
    assert "Last refresh: clean" in response.text


@pytest.mark.asyncio
async def test_wiki_refresh_fragment_endpoint_returns_404_for_unknown_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown project → 404, same contract as /project/<slug>."""
    _seed_project(tmp_path, monkeypatch)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/project/does-not-exist/wiki-refresh")
    assert response.status_code == 404
