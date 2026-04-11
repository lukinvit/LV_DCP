from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from libs.mcp_ops.launchd import (
    LAUNCH_AGENT_LABEL,
    LaunchctlError,
    bootout_agent,
    bootstrap_agent,
    write_plist,
)


def test_write_plist_creates_file_with_label(tmp_path: Path) -> None:
    target = tmp_path / f"{LAUNCH_AGENT_LABEL}.plist"
    write_plist(
        target_path=target,
        program_arguments=["/usr/bin/python", "-m", "apps.agent.daemon"],
        log_dir=tmp_path / "logs",
    )
    assert target.exists()
    content = target.read_text()
    assert LAUNCH_AGENT_LABEL in content
    assert "/usr/bin/python" in content


def test_write_plist_creates_log_dir(tmp_path: Path) -> None:
    target = tmp_path / f"{LAUNCH_AGENT_LABEL}.plist"
    log_dir = tmp_path / "sub" / "logs"
    write_plist(
        target_path=target,
        program_arguments=["/usr/bin/python", "-m", "apps.agent.daemon"],
        log_dir=log_dir,
    )
    assert log_dir.exists()


def test_bootstrap_agent_invokes_launchctl() -> None:
    with patch("libs.mcp_ops.launchd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        bootstrap_agent(plist_path=Path("/tmp/x.plist"), uid=501)
        args = mock_run.call_args[0][0]
        assert args[:3] == ["launchctl", "bootstrap", "gui/501"]
        assert args[3] == "/tmp/x.plist"


def test_bootstrap_agent_raises_on_error() -> None:
    with patch("libs.mcp_ops.launchd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=5, stdout="", stderr="requires GUI")
        with pytest.raises(LaunchctlError, match="GUI"):
            bootstrap_agent(plist_path=Path("/tmp/x.plist"), uid=501)


def test_bootout_agent_invokes_launchctl() -> None:
    with patch("libs.mcp_ops.launchd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        bootout_agent(uid=501)
        args = mock_run.call_args[0][0]
        assert args == ["launchctl", "bootout", f"gui/501/{LAUNCH_AGENT_LABEL}"]


def test_bootout_agent_raises_on_error() -> None:
    with patch("libs.mcp_ops.launchd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=3, stdout="", stderr="not loaded")
        with pytest.raises(LaunchctlError, match="not loaded"):
            bootout_agent(uid=501)
