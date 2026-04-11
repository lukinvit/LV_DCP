"""Integration test: real `claude mcp add/remove` round-trip.

Skipped unless the `claude` CLI is on PATH. Uses a temp HOME to avoid
touching the user's real ~/.claude configuration.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from libs.mcp_ops.install import install_lvdcp
from libs.mcp_ops.uninstall import uninstall_lvdcp

pytestmark = pytest.mark.requires_claude_cli


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


def test_real_install_uninstall_roundtrip(isolated_home: Path) -> None:
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not on PATH")

    claudemd = isolated_home / ".claude" / "CLAUDE.md"
    config = isolated_home / ".lvdcp" / "config.yaml"

    install_lvdcp(
        claudemd_path=claudemd,
        config_path=config,
        entry_command="/usr/bin/python",
        entry_args=["-m", "apps.mcp.server"],
        scope="user",
        version="0.0.0-test",
    )
    proc = subprocess.run(
        ["claude", "mcp", "list"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0
    assert "lvdcp" in proc.stdout

    uninstall_lvdcp(claudemd_path=claudemd, scope="user")
    proc = subprocess.run(
        ["claude", "mcp", "list"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert "lvdcp" not in proc.stdout
