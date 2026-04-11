"""Integration tests: file summaries display in /project/<slug> detail view."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import yaml
from apps.agent.config import add_project
from apps.ui.main import create_app
from libs.scanning.scanner import scan_project
from libs.summaries.store import SummaryRow, SummaryStore


@pytest.fixture
def workspace_with_summaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    (project / "b.py").write_text("def b() -> None: return None\n")
    scan_project(project, mode="full")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"version": 1, "projects": []}))
    add_project(cfg, project)

    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))

    # Populate summaries for a.py and b.py
    store = SummaryStore(tmp_path / "summaries.db")
    store.migrate()
    store.persist(
        SummaryRow(
            content_hash="h1",
            prompt_version="v2",
            model_name="gpt-4o-mini",
            project_root=str(project.resolve()),
            file_path="a.py",
            summary_text="Defines function a() that returns None.",
            cost_usd=0.00032,
            tokens_in=100,
            tokens_out=20,
            tokens_cached=0,
            created_at=time.time(),
        )
    )
    store.persist(
        SummaryRow(
            content_hash="h2",
            prompt_version="v2",
            model_name="gpt-4o-mini",
            project_root=str(project.resolve()),
            file_path="b.py",
            summary_text="Defines function b() that returns None.",
            cost_usd=0.00032,
            tokens_in=100,
            tokens_out=20,
            tokens_cached=0,
            created_at=time.time(),
        )
    )
    store.close()
    return project


@pytest.mark.asyncio
async def test_project_detail_shows_summaries_section(workspace_with_summaries: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/project/{workspace_with_summaries.name.lower().replace('_', '-')}"
        )
    assert response.status_code == 200
    # Verify the summaries section header is present
    assert "File summaries" in response.text or "summaries" in response.text.lower()
    # Verify at least one summary text is rendered
    assert "Defines function a()" in response.text
    assert "Defines function b()" in response.text


@pytest.mark.asyncio
async def test_project_detail_without_summaries_shows_empty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def a() -> None: return None\n")
    scan_project(project, mode="full")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"version": 1, "projects": []}))
    add_project(cfg, project)

    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/project/{project.name.lower().replace('_', '-')}")
    assert response.status_code == 200
    # Empty state message should be present
    assert "No summaries" in response.text or "ctx summarize" in response.text
