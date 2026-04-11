import json
from pathlib import Path

from apps.mcp.install import (
    install_claudemd_section,
    install_mcp_settings,
    uninstall_claudemd_section,
    uninstall_mcp_settings,
)


def test_install_claudemd_section_adds_sentinel_block(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text("# My personal rules\n\nSome content here.\n")

    install_claudemd_section(claudemd)

    content = claudemd.read_text()
    assert "<!-- LV_DCP-managed-section:start:v1 -->" in content
    assert "<!-- LV_DCP-managed-section:end:v1 -->" in content
    assert "lvdcp_pack" in content


def test_install_creates_backup(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text("existing content\n")

    install_claudemd_section(claudemd)

    # backup files end in .lvdcp-backup-<timestamp>
    backups = list(tmp_path.glob("CLAUDE.md.lvdcp-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "existing content\n"


def test_install_is_idempotent(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text("base\n")

    install_claudemd_section(claudemd)
    first = claudemd.read_text()

    install_claudemd_section(claudemd)
    second = claudemd.read_text()

    # Same content (modulo backup files)
    assert first.count("LV_DCP-managed-section:start") == 1
    assert second.count("LV_DCP-managed-section:start") == 1


def test_install_creates_file_if_missing(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    assert not claudemd.exists()

    install_claudemd_section(claudemd)

    assert claudemd.exists()
    assert "LV_DCP-managed-section:start:v1" in claudemd.read_text()


def test_uninstall_removes_managed_section(tmp_path: Path) -> None:
    claudemd = tmp_path / "CLAUDE.md"
    claudemd.write_text("before\n")

    install_claudemd_section(claudemd)
    assert "LV_DCP-managed-section" in claudemd.read_text()

    uninstall_claudemd_section(claudemd)
    content = claudemd.read_text()
    assert "LV_DCP-managed-section" not in content
    assert "before" in content


def test_install_mcp_settings_writes_json(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"

    install_mcp_settings(settings, entry_point="/usr/bin/python -m apps.mcp.server")

    data = json.loads(settings.read_text())
    assert "mcpServers" in data
    assert "lvdcp" in data["mcpServers"]
    assert data["mcpServers"]["lvdcp"]["command"].startswith("/usr/bin/python")


def test_install_mcp_settings_merges_with_existing(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"otherKey": "keep me", "mcpServers": {"existing": {"command": "x"}}})
    )

    install_mcp_settings(settings, entry_point="python -m apps.mcp.server")

    data = json.loads(settings.read_text())
    assert data["otherKey"] == "keep me"
    assert "existing" in data["mcpServers"]
    assert "lvdcp" in data["mcpServers"]


def test_uninstall_mcp_settings_removes_only_lvdcp(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "lvdcp": {"command": "python"},
                    "other": {"command": "other"},
                }
            }
        )
    )

    uninstall_mcp_settings(settings)

    data = json.loads(settings.read_text())
    assert "lvdcp" not in data["mcpServers"]
    assert "other" in data["mcpServers"]


def test_uninstall_mcp_settings_noop_if_missing(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    assert not settings.exists()

    # Should not raise
    uninstall_mcp_settings(settings)

    assert not settings.exists()
