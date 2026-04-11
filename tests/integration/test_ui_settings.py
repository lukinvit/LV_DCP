"""Integration tests for /settings route and /api/settings/test-connection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import yaml
from apps.ui.main import create_app


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"version": 1, "projects": []}))
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("LVDCP_SUMMARIES_DB", str(tmp_path / "summaries.db"))
    monkeypatch.setenv("LVDCP_CLAUDE_PROJECTS_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("LVDCP_USAGE_CACHE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("LVDCP_SCAN_HISTORY_DB", str(tmp_path / "history.db"))
    return cfg


async def test_settings_page_renders(isolated: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings")
    assert response.status_code == 200
    assert "gpt-4o-mini" in response.text


async def test_settings_page_shows_all_providers(isolated: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings")
    for provider in ("openai", "anthropic", "ollama"):
        assert provider in response.text


async def test_settings_post_writes_config(isolated: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/settings",
            data={
                "provider": "anthropic",
                "summary_model": "claude-haiku-4-5",
                "rerank_model": "claude-haiku-4-5",
                "api_key_env_var": "ANTHROPIC_API_KEY",
                "monthly_budget_usd": "50",
                "enabled": "on",
            },
            follow_redirects=False,
        )
    assert response.status_code in (200, 303)

    cfg_data = yaml.safe_load(isolated.read_text())  # noqa: ASYNC240
    assert cfg_data["llm"]["provider"] == "anthropic"
    assert cfg_data["llm"]["enabled"] is True
    assert cfg_data["llm"]["monthly_budget_usd"] == 50.0


async def test_test_connection_endpoint(isolated: Path) -> None:
    mock_client = AsyncMock()
    mock_client.test_connection = AsyncMock(return_value=True)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    with patch("apps.ui.routes.settings.create_client", return_value=mock_client):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/settings/test-connection")
    assert response.status_code == 200
    # Now returns HTML fragment, not JSON
    assert "test-ok" in response.text
    assert "Connected" in response.text


async def test_settings_post_redirects_with_saved_flag(isolated: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/settings",
            data={
                "provider": "openai",
                "summary_model": "gpt-4o-mini",
                "rerank_model": "gpt-4o-mini",
                "api_key_env_var": "OPENAI_API_KEY",
                "monthly_budget_usd": "25",
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "saved=1" in response.headers["location"]


async def test_settings_page_shows_flash_when_saved(isolated: Path) -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings?saved=1")
    assert response.status_code == 200
    assert "Settings saved" in response.text or "flash-success" in response.text
