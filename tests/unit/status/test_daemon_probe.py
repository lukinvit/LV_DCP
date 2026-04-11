from __future__ import annotations

from unittest.mock import MagicMock, patch

from libs.status.daemon_probe import probe_daemon


def test_probe_running() -> None:
    with patch("libs.status.daemon_probe.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="0\t-\ttech.lvdcp.agent\n", stderr=""
        )
        status = probe_daemon()
    assert status.state == "running"
    assert status.detail == "loaded and active"


def test_probe_not_loaded() -> None:
    with patch("libs.status.daemon_probe.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=113, stdout="", stderr="Could not find service")
        status = probe_daemon()
    assert status.state == "not_loaded"


def test_probe_error() -> None:
    with patch("libs.status.daemon_probe.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=37, stdout="", stderr="permission denied")
        status = probe_daemon()
    assert status.state == "error"
    assert "permission denied" in status.detail


def test_probe_missing_launchctl() -> None:
    with patch("libs.status.daemon_probe.subprocess.run", side_effect=FileNotFoundError):
        status = probe_daemon()
    assert status.state == "error"
    assert "launchctl" in status.detail.lower()
