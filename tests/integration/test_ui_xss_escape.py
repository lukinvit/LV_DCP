from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from apps.agent.config import add_project
from apps.ui.main import create_app
from libs.scanning.scanner import scan_project


async def test_project_name_is_html_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Use a project whose name contains '&', a POSIX-valid character that
    # must be HTML-escaped to '&amp;'.  Without autoescape an injected
    # '&something;' entity could be rendered by the browser.
    project = tmp_path / "evil&project"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n")
    scan_project(project, mode="full")

    cfg = tmp_path / "config.yaml"
    add_project(cfg, project)
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    # Jinja2 autoescape must convert '&' -> '&amp;'.
    # The escaped project name must appear in the page.
    assert "evil&amp;project" in response.text
    # The raw unescaped form must NOT appear as a standalone token.
    # (response.text contains "evil&amp;project" not "evil&project" unescaped)
    assert "evil&project" not in response.text.replace("evil&amp;project", "")
