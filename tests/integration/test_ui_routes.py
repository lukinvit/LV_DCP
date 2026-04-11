"""Integration tests for UI dashboard routes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from apps.agent.config import add_project
from apps.ui.main import create_app
from libs.scanning.scanner import scan_project


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("from b import f\n")
    (project / "b.py").write_text("def f() -> None: return None\n")
    scan_project(project, mode="full")

    cfg = tmp_path / "config.yaml"
    add_project(cfg, project)
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    return project


async def test_index_route_renders_html(workspace: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "Projects" in response.text
    assert workspace.name in response.text


async def test_project_detail_route(workspace: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{workspace.name.lower().replace('_', '-')}")
    assert response.status_code == 200
    assert "Dependency graph" in response.text
    assert "Sparklines" in response.text


async def test_api_graph_json_route(workspace: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{workspace.name.lower().replace('_', '-')}/graph.json"
        )
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data


async def test_api_sparklines_json_route(workspace: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/project/{workspace.name.lower().replace('_', '-')}/sparklines.json"
        )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    metrics = {s["metric"] for s in data}
    assert {"queries", "scans", "latency_p95_ms", "coverage"} == metrics


async def test_project_not_found_returns_404(workspace: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/project/no-such-project")
    assert response.status_code == 404
