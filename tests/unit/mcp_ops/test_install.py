from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from libs.mcp_ops.claude_cli import ClaudeCliError
from libs.mcp_ops.install import (
    MANAGED_SECTION_END,
    MANAGED_SECTION_START,
    InstallResult,
    build_dry_run_snippet,
    install_lvdcp,
)


def test_install_fails_without_claude_cli(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    config = tmp_path / "config.yaml"

    with (
        patch("libs.mcp_ops.install.has_claude_cli", return_value=False),
        pytest.raises(ClaudeCliError, match="not found"),
    ):
        install_lvdcp(
            claudemd_path=claudemd,
            config_path=config,
            entry_command="/usr/bin/python",
            entry_args=["-m", "apps.mcp.server"],
            scope="user",
            version="0.0.0",
        )
    assert not config.exists()


def test_install_creates_empty_config_yaml(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    config = tmp_path / "config.yaml"

    with (
        patch("libs.mcp_ops.install.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.install.claude_mcp_add"),
    ):
        result = install_lvdcp(
            claudemd_path=claudemd,
            config_path=config,
            entry_command="/usr/bin/python",
            entry_args=["-m", "apps.mcp.server"],
            scope="user",
            version="0.0.0",
        )

    assert config.exists()
    data = yaml.safe_load(config.read_text())
    assert data == {"version": 1, "projects": []}
    assert result.config_created is True


def test_install_writes_managed_section_with_version(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    config = tmp_path / "config.yaml"

    with (
        patch("libs.mcp_ops.install.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.install.claude_mcp_add"),
    ):
        install_lvdcp(
            claudemd_path=claudemd,
            config_path=config,
            entry_command="/usr/bin/python",
            entry_args=["-m", "apps.mcp.server"],
            scope="user",
            version="1.2.3",
        )

    content = claudemd.read_text()
    assert MANAGED_SECTION_START in content
    assert MANAGED_SECTION_END in content
    assert "lvdcp-managed-version: 1.2.3" in content
    assert "lvdcp_pack" in content


def test_install_idempotent_on_claude_md(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text("# My rules\n")
    config = tmp_path / "config.yaml"

    with (
        patch("libs.mcp_ops.install.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.install.claude_mcp_add"),
    ):
        install_lvdcp(
            claudemd_path=claudemd,
            config_path=config,
            entry_command="/usr/bin/python",
            entry_args=["-m", "apps.mcp.server"],
            scope="user",
            version="1.2.3",
        )
        install_lvdcp(
            claudemd_path=claudemd,
            config_path=config,
            entry_command="/usr/bin/python",
            entry_args=["-m", "apps.mcp.server"],
            scope="user",
            version="1.2.3",
        )

    content = claudemd.read_text()
    assert content.count(MANAGED_SECTION_START) == 1
    assert content.count(MANAGED_SECTION_END) == 1


def test_build_dry_run_snippet_returns_valid_json() -> None:
    snippet = build_dry_run_snippet(
        server_name="lvdcp",
        command="/usr/bin/python",
        args=["-m", "apps.mcp.server"],
        scope="user",
    )
    parsed = json.loads(snippet)
    assert parsed["mcpServers"]["lvdcp"]["command"] == "/usr/bin/python"
    assert parsed["mcpServers"]["lvdcp"]["args"] == ["-m", "apps.mcp.server"]


def test_install_result_carries_entry_point(tmp_path: Path) -> None:
    with (
        patch("libs.mcp_ops.install.has_claude_cli", return_value=True),
        patch("libs.mcp_ops.install.claude_mcp_add"),
    ):
        result = install_lvdcp(
            claudemd_path=tmp_path / "CLAUDE.md",
            config_path=tmp_path / "config.yaml",
            entry_command="/abs/bin/python",
            entry_args=["-m", "apps.mcp.server"],
            scope="user",
            version="0.0.0",
        )
    assert isinstance(result, InstallResult)
    assert result.entry_command == "/abs/bin/python"
    assert result.scope == "user"
