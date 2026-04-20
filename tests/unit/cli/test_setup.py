"""Tests for `ctx setup` onboarding orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest
from apps.cli.commands import mcp_cmd, wiki_cmd
from apps.cli.commands import scan as scan_module
from apps.cli.commands import setup as setup_cmd
from apps.cli.commands import ui as ui_module
from apps.cli.main import app
from libs.core.projects_config import DaemonConfig, EmbeddingConfig, QdrantConfig, load_config
from typer.testing import CliRunner

runner = CliRunner()


def test_setup_enables_wiki_and_reports_full_mode_gaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(setup_cmd, "DEFAULT_CONFIG_PATH", config_path)

    called: list[str] = []

    def fake_scan(path: Path, *, full: bool = False) -> None:
        called.append(f"scan:{path.name}:{full}")

    def fake_install(*, scope: str = "user", dry_run: bool = False) -> None:
        called.append(f"mcp:{scope}:{dry_run}")

    def fake_wiki_update(project_path: Path, *, all_modules: bool = False) -> None:
        called.append(f"wiki:{project_path.name}:{all_modules}")

    monkeypatch.setattr(scan_module, "scan", fake_scan)
    monkeypatch.setattr(mcp_cmd, "install", fake_install)
    monkeypatch.setattr(wiki_cmd, "update", fake_wiki_update)
    monkeypatch.setattr(setup_cmd, "_has_claude_cli", lambda: True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(app, ["setup", str(project), "--no-install-service"])

    assert result.exit_code == 0
    cfg = load_config(config_path)
    assert cfg.wiki.enabled is True
    assert cfg.wiki.auto_update_after_scan is True
    assert "base mode: ready" in result.stdout
    assert "wiki: ready" in result.stdout
    assert "full mode: degraded" in result.stdout
    assert "Qdrant disabled" in result.stdout
    assert "OPENAI_API_KEY env var not set" in result.stdout
    assert called == [
        "scan:project:False",
        "mcp:user:False",
        "wiki:project:False",
    ]


def test_setup_skips_mcp_and_wiki_when_claude_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(setup_cmd, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(scan_module, "scan", lambda path, *, full=False: None)
    monkeypatch.setattr(setup_cmd, "_has_claude_cli", lambda: False)

    result = runner.invoke(app, ["setup", str(project), "--no-install-service"])

    assert result.exit_code == 0
    cfg = load_config(config_path)
    assert cfg.wiki.enabled is False
    assert "mcp: skipped" in result.stdout
    assert "Claude CLI missing — MCP install skipped" in result.stdout
    assert "wiki: degraded" in result.stdout
    assert "Claude CLI missing — wiki not enabled" in result.stdout


def test_setup_opens_ui_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(setup_cmd, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(scan_module, "scan", lambda path, *, full=False: None)
    monkeypatch.setattr(setup_cmd, "_has_claude_cli", lambda: False)

    opened: list[Path] = []
    monkeypatch.setattr(ui_module, "ui", lambda path: opened.append(path))

    result = runner.invoke(
        app,
        [
            "setup",
            str(project),
            "--no-wiki",
            "--no-install-service",
            "--open-ui",
        ],
    )

    assert result.exit_code == 0
    assert opened == [project]


def test_full_mode_status_ready_when_qdrant_and_embeddings_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = DaemonConfig(
        qdrant=QdrantConfig(enabled=True, url="http://127.0.0.1:6333"),
        embedding=EmbeddingConfig(
            provider="openai",
            api_key_env_var="OPENAI_API_KEY",
        ),
    )
    monkeypatch.setattr(setup_cmd, "_qdrant_reachable", lambda url: True)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    status = setup_cmd._full_mode_status(cfg)

    assert status.state == "ready"
    assert status.detail == "Qdrant + embeddings ready"
