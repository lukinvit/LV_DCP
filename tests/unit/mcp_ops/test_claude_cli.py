from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from libs.mcp_ops.claude_cli import (
    CLAUDE_BIN,
    ClaudeCliError,
    claude_mcp_add,
    claude_mcp_list,
    claude_mcp_remove,
    has_claude_cli,
)


def test_has_claude_cli_true_when_which_returns_path() -> None:
    with patch("libs.mcp_ops.claude_cli.shutil.which", return_value="/usr/local/bin/claude"):
        assert has_claude_cli() is True


def test_has_claude_cli_false_when_which_returns_none() -> None:
    with patch("libs.mcp_ops.claude_cli.shutil.which", return_value=None):
        assert has_claude_cli() is False


def test_claude_mcp_add_invokes_correct_subprocess() -> None:
    with patch("libs.mcp_ops.claude_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        claude_mcp_add(
            server_name="lvdcp",
            command="/usr/bin/python",
            args=["-m", "apps.mcp.server"],
            scope="user",
        )
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        assert cmd_args[:5] == [CLAUDE_BIN, "mcp", "add", "--scope", "user"]
        assert "lvdcp" in cmd_args
        assert "--" in cmd_args
        assert "/usr/bin/python" in cmd_args
        assert "-m" in cmd_args
        assert "apps.mcp.server" in cmd_args


def test_claude_mcp_add_raises_on_non_zero_exit() -> None:
    with patch("libs.mcp_ops.claude_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        with pytest.raises(ClaudeCliError) as exc_info:
            claude_mcp_add(
                server_name="lvdcp",
                command="python",
                args=["-m", "apps.mcp.server"],
                scope="user",
            )
        assert "boom" in str(exc_info.value)


def test_claude_mcp_add_raises_on_missing_binary() -> None:
    with patch("libs.mcp_ops.claude_cli.subprocess.run", side_effect=FileNotFoundError), pytest.raises(ClaudeCliError, match="not found"):
        claude_mcp_add(
            server_name="lvdcp",
            command="python",
            args=[],
            scope="user",
        )


def test_claude_mcp_remove_invokes_correct_subprocess() -> None:
    with patch("libs.mcp_ops.claude_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        claude_mcp_remove(server_name="lvdcp", scope="user")
        cmd_args = mock_run.call_args[0][0]
        assert cmd_args[:3] == [CLAUDE_BIN, "mcp", "remove"]
        assert "--scope" in cmd_args
        assert "user" in cmd_args
        assert "lvdcp" in cmd_args


def test_claude_mcp_list_returns_stdout() -> None:
    with patch("libs.mcp_ops.claude_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="lvdcp: Connected\n", stderr="")
        out = claude_mcp_list()
        assert "lvdcp" in out
        assert "Connected" in out


def test_claude_mcp_list_raises_on_missing_binary() -> None:
    with patch("libs.mcp_ops.claude_cli.subprocess.run", side_effect=FileNotFoundError), pytest.raises(ClaudeCliError, match="not found"):
        claude_mcp_list()
