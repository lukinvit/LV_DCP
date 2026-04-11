from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from libs.mcp_ops.uninstall import (
    LegacyCleanResult,
    clean_legacy_settings_json,
    uninstall_lvdcp,
)


def test_uninstall_removes_managed_section(tmp_path: Path) -> None:
    from libs.mcp_ops.install import MANAGED_SECTION_END, MANAGED_SECTION_START

    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text(f"# Keep me\n\n{MANAGED_SECTION_START}\nstuff\n{MANAGED_SECTION_END}\n")

    with patch("libs.mcp_ops.uninstall.claude_mcp_remove"):
        uninstall_lvdcp(claudemd_path=claudemd, scope="user")

    content = claudemd.read_text()
    assert MANAGED_SECTION_START not in content
    assert MANAGED_SECTION_END not in content
    assert "# Keep me" in content


def test_uninstall_noop_if_claudemd_missing(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    assert not claudemd.exists()
    with patch("libs.mcp_ops.uninstall.claude_mcp_remove"):
        uninstall_lvdcp(claudemd_path=claudemd, scope="user")
    assert not claudemd.exists()


def test_uninstall_tolerates_claude_remove_error(tmp_path: Path) -> None:
    from libs.mcp_ops.claude_cli import ClaudeCliError

    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text("# keep\n")

    with patch(
        "libs.mcp_ops.uninstall.claude_mcp_remove",
        side_effect=ClaudeCliError("not installed"),
    ):
        # Should not re-raise: local cleanup proceeds regardless
        uninstall_lvdcp(claudemd_path=claudemd, scope="user")

    assert claudemd.read_text() == "# keep\n"


def test_clean_legacy_settings_removes_lvdcp_entry(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "lvdcp": {"command": "old", "args": []},
                    "other": {"command": "ok"},
                },
                "permissions": {"allow": ["Bash"]},
            }
        )
    )

    result = clean_legacy_settings_json(settings)
    assert isinstance(result, LegacyCleanResult)
    assert result.removed is True

    data = json.loads(settings.read_text())
    assert "lvdcp" not in data["mcpServers"]
    assert "other" in data["mcpServers"]
    assert data["permissions"] == {"allow": ["Bash"]}


def test_clean_legacy_settings_removes_empty_mcp_servers_key(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"mcpServers": {"lvdcp": {"command": "old"}}}))

    clean_legacy_settings_json(settings)

    data = json.loads(settings.read_text())
    assert "mcpServers" not in data or data["mcpServers"] == {}


def test_clean_legacy_settings_noop_if_no_lvdcp(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    original = {"mcpServers": {"other": {"command": "x"}}}
    settings.write_text(json.dumps(original))

    result = clean_legacy_settings_json(settings)
    assert result.removed is False
    assert json.loads(settings.read_text()) == original


def test_clean_legacy_settings_noop_if_file_missing(tmp_path: Path) -> None:
    settings = tmp_path / "nothing.json"
    result = clean_legacy_settings_json(settings)
    assert result.removed is False
