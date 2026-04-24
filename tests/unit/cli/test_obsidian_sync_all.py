"""Tests for `ctx obsidian sync-all` (v0.8.28 nightly sync)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from apps.cli.commands.obsidian_cmd import _OBSIDIAN_MARKER
from apps.cli.main import app
from typer.testing import CliRunner


def _write_config(
    cfg_path: Path,
    *,
    vault_path: str,
    projects: list[Path],
    enabled: bool = True,
) -> None:
    """Write a minimal ~/.lvdcp/config.yaml for the sync-all command."""
    payload: dict[str, object] = {
        "obsidian": {
            "enabled": enabled,
            "vault_path": vault_path,
            "sync_mode": "manual",
            "auto_sync_after_scan": False,
            "debounce_seconds": 3600,
        },
        "projects": [
            {
                "root": str(root),
                "registered_at_iso": "2026-04-24T00:00:00Z",
                "last_scan_status": "ok",
            }
            for root in projects
        ],
    }
    cfg_path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _seed_project(root: Path, *, with_cache: bool = True) -> None:
    """Create `root/.context/cache.db` so sync-all treats it as scanned."""
    root.mkdir(parents=True, exist_ok=True)
    if with_cache:
        ctx = root / ".context"
        ctx.mkdir(parents=True, exist_ok=True)
        (ctx / "cache.db").write_bytes(b"")


def _write_marker(root: Path, ts: float) -> None:
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / _OBSIDIAN_MARKER).write_text(str(ts), encoding="utf-8")


# ---- Config validation -----------------------------------------------------


def test_missing_config_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["obsidian", "sync-all", "--config", str(tmp_path / "missing.yaml")],
    )
    assert result.exit_code == 1
    # error on stderr via typer.echo(..., err=True); CliRunner merges by default
    assert "config not found" in result.output or "config not found" in (result.stderr or "")


def test_obsidian_disabled_exits_clean(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[], enabled=False)
    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "disabled" in result.output.lower()


def test_empty_vault_path_exits_nonzero(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path="", projects=[tmp_path / "p"])
    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "vault_path" in result.output or "vault_path" in (result.stderr or "")


def test_no_projects_exits_clean(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[])
    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "No registered projects" in result.output


# ---- Dry-run plan ---------------------------------------------------------


def test_dry_run_prints_sync_for_fresh_project(tmp_path: Path) -> None:
    """A never-synced project shows as `sync` in the plan without invoking subprocess."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        result = runner.invoke(
            app,
            ["obsidian", "sync-all", "--config", str(cfg), "--dry-run"],
        )
    assert result.exit_code == 0, result.output
    assert "sync" in result.output
    assert str(proj) in result.output
    mock_run.assert_not_called()


def test_dry_run_marks_cacheless_project_as_skip(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _seed_project(proj, with_cache=False)  # no .context/cache.db
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["obsidian", "sync-all", "--config", str(cfg), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "skip: no cache.db" in result.output


def test_dry_run_marks_fresh_project_as_skip_with_age(tmp_path: Path) -> None:
    """Recently-synced project shows `skip: fresh (Xh old)`."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    _write_marker(proj, time.time() - 600)  # 10 minutes ago
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["obsidian", "sync-all", "--config", str(cfg), "--dry-run", "--stale-hours", "24"],
    )
    assert result.exit_code == 0, result.output
    assert "skip: fresh" in result.output


def test_dry_run_stale_hours_zero_forces_all_to_sync(tmp_path: Path) -> None:
    """`--stale-hours 0` treats every project as stale, including fresh ones."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    _write_marker(proj, time.time())  # just synced
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["obsidian", "sync-all", "--config", str(cfg), "--dry-run", "--stale-hours", "0"],
    )
    assert result.exit_code == 0, result.output
    # Exactly one project, must appear as "sync", not "skip"
    assert "sync" in result.output
    assert "skip: fresh" not in result.output


# ---- Live sync -----------------------------------------------------------


def test_sync_invokes_ctx_obsidian_sync_and_updates_marker(tmp_path: Path) -> None:
    """Happy path: stale project → subprocess called → marker advanced."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    vault = tmp_path / "vault"
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(vault), projects=[proj])

    before = time.time()
    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    # Must re-invoke our own CLI via `python -m apps.cli.main obsidian sync`
    assert "obsidian" in args
    assert "sync" in args
    assert str(proj) in args
    assert str(vault) in args

    # Marker must exist and be recent
    marker = proj / ".context" / _OBSIDIAN_MARKER
    assert marker.exists()
    written_ts = float(marker.read_text(encoding="utf-8"))
    assert written_ts >= before

    assert "Synced: 1" in result.output


def test_fresh_project_is_skipped_no_subprocess(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _seed_project(proj)
    _write_marker(proj, time.time() - 60)  # 1 min ago
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        result = runner.invoke(
            app, ["obsidian", "sync-all", "--config", str(cfg), "--stale-hours", "24"]
        )
    assert result.exit_code == 0, result.output
    mock_run.assert_not_called()
    assert "Synced: 0" in result.output
    assert "skipped: 1" in result.output


def test_mixed_plan_syncs_only_stale_projects(tmp_path: Path) -> None:
    """Two projects: one fresh, one stale → subprocess called exactly once."""
    fresh = tmp_path / "fresh"
    stale = tmp_path / "stale"
    _seed_project(fresh)
    _seed_project(stale)
    _write_marker(fresh, time.time() - 60)  # fresh
    _write_marker(stale, time.time() - 7200)  # 2h old, stale under 1h gate
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[fresh, stale])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        result = runner.invoke(
            app, ["obsidian", "sync-all", "--config", str(cfg), "--stale-hours", "1"]
        )
    assert result.exit_code == 0, result.output
    assert mock_run.call_count == 1
    invoked_args = mock_run.call_args.args[0]
    assert str(stale) in invoked_args
    assert str(fresh) not in invoked_args


def test_subprocess_failure_exits_1_but_runs_others(tmp_path: Path) -> None:
    """One flaky project doesn't block the rest. Exit code 1 if any failed."""
    bad = tmp_path / "bad"
    good = tmp_path / "good"
    _seed_project(bad)
    _seed_project(good)
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[bad, good])

    def _fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        if str(bad) in cmd:
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output=b"", stderr=b"boom")
        return MagicMock(returncode=0, stdout=b"", stderr=b"")

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run", side_effect=_fake_run) as mock_run:
        result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])

    assert result.exit_code == 1, result.output
    assert mock_run.call_count == 2  # both attempted
    # Failed project must NOT have a marker
    assert not (bad / ".context" / _OBSIDIAN_MARKER).exists()
    # Succeeded project MUST have a marker
    assert (good / ".context" / _OBSIDIAN_MARKER).exists()
    assert "failed: 1" in result.output


def test_subprocess_timeout_is_reported_as_failure(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _seed_project(proj)
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ctx"], timeout=1)
        result = runner.invoke(
            app, ["obsidian", "sync-all", "--config", str(cfg), "--timeout", "1"]
        )
    assert result.exit_code == 1, result.output
    assert not (proj / ".context" / _OBSIDIAN_MARKER).exists()
    assert "failed: 1" in result.output


def test_nonexistent_project_root_is_skipped(tmp_path: Path) -> None:
    """Stale entry for a deleted project dir → skip, not crash."""
    ghost = tmp_path / "gone"  # never created
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[ghost])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    mock_run.assert_not_called()


# ---- Helper gate semantics ------------------------------------------------


@pytest.mark.parametrize(
    ("marker_age_s", "stale_hours", "should_sync"),
    [
        (None, 24, True),  # never synced → stale
        (60, 24, False),  # 1 min ago under 24h gate → fresh
        (25 * 3600, 24, True),  # 25h ago → stale
        (10 * 3600, 0, True),  # any marker with --stale-hours 0 → force
    ],
)
def test_is_stale_gate(
    tmp_path: Path, marker_age_s: float | None, stale_hours: float, should_sync: bool
) -> None:
    from apps.cli.commands.obsidian_cmd import _is_stale

    proj = tmp_path / "p"
    proj.mkdir()
    if marker_age_s is not None:
        _write_marker(proj, time.time() - marker_age_s)
    assert _is_stale(proj, stale_hours * 3600.0, time.time()) is should_sync
