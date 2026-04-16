"""Tests for apps/agent/obsidian_worker.py — debounced Obsidian vault sync."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from libs.core.projects_config import ObsidianConfig


def _fresh_config(tmp_path: Path) -> ObsidianConfig:
    return ObsidianConfig(
        enabled=True,
        vault_path=str(tmp_path / "vault"),
        auto_sync_after_scan=True,
        debounce_seconds=3600,
    )


class TestDebounceGate:
    def test_first_run_proceeds(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import run_obsidian_sync

        project_root = tmp_path / "proj"
        project_root.mkdir()
        cfg = _fresh_config(tmp_path)

        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is True
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        assert "obsidian" in args
        assert "sync" in args
        assert str(project_root) in args

    def test_within_debounce_skipped(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import _OBSIDIAN_MARKER, run_obsidian_sync

        project_root = tmp_path / "proj"
        ctx_dir = project_root / ".context"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / _OBSIDIAN_MARKER).write_text(str(time.time()), encoding="utf-8")
        cfg = _fresh_config(tmp_path)

        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is False
        mock_run.assert_not_called()

    def test_after_debounce_runs(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import _OBSIDIAN_MARKER, run_obsidian_sync

        project_root = tmp_path / "proj"
        ctx_dir = project_root / ".context"
        ctx_dir.mkdir(parents=True)
        stale_ts = time.time() - 7200
        (ctx_dir / _OBSIDIAN_MARKER).write_text(str(stale_ts), encoding="utf-8")
        cfg = _fresh_config(tmp_path)

        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is True

    def test_marker_updated_after_success(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import _OBSIDIAN_MARKER, run_obsidian_sync

        project_root = tmp_path / "proj"
        project_root.mkdir()
        cfg = _fresh_config(tmp_path)

        before = time.time()
        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            run_obsidian_sync(project_root, cfg)
        marker = project_root / ".context" / _OBSIDIAN_MARKER
        assert marker.exists()
        written_ts = float(marker.read_text(encoding="utf-8"))
        assert written_ts >= before

    def test_disabled_config_never_runs(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import run_obsidian_sync

        project_root = tmp_path / "proj"
        project_root.mkdir()
        cfg = ObsidianConfig(
            enabled=False,
            vault_path=str(tmp_path / "vault"),
            auto_sync_after_scan=True,
        )
        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is False
        mock_run.assert_not_called()

    def test_empty_vault_path_never_runs(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import run_obsidian_sync

        project_root = tmp_path / "proj"
        project_root.mkdir()
        cfg = ObsidianConfig(enabled=True, vault_path="", auto_sync_after_scan=True)
        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is False
        mock_run.assert_not_called()

    def test_subprocess_failure_does_not_update_marker(self, tmp_path: Path) -> None:
        """If ctx obsidian sync exits non-zero, marker must NOT advance."""
        from apps.agent.obsidian_worker import _OBSIDIAN_MARKER, run_obsidian_sync

        project_root = tmp_path / "proj"
        project_root.mkdir()
        cfg = _fresh_config(tmp_path)

        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["ctx"], output=b"", stderr=b"boom"
            )
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is False
        marker = project_root / ".context" / _OBSIDIAN_MARKER
        assert not marker.exists()

    def test_subprocess_timeout_does_not_update_marker(self, tmp_path: Path) -> None:
        from apps.agent.obsidian_worker import _OBSIDIAN_MARKER, run_obsidian_sync

        project_root = tmp_path / "proj"
        project_root.mkdir()
        cfg = _fresh_config(tmp_path)

        with patch("apps.agent.obsidian_worker.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ctx"], timeout=300)
            ran = run_obsidian_sync(project_root, cfg)
        assert ran is False
        assert not (project_root / ".context" / _OBSIDIAN_MARKER).exists()
