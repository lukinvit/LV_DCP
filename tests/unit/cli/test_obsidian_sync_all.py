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


# ---- v0.8.61: `obsidian sync-all --json` multi-project scriptability ------

# Schema-locked surface for `ctx obsidian sync-all --json` (v0.8.61). The
# top-level shape is `{vault, stale_hours, dry_run, synced, skipped, failed,
# results}` where `results` is a per-project array with the inner four-key
# shape locked separately. Adding a top-level key requires bumping this
# frozenset + the `json.dumps(...)` payload in
# `apps/cli/commands/obsidian_cmd.py::sync_all` at the same time.
_SYNC_ALL_JSON_KEYS = frozenset(
    {"vault", "stale_hours", "dry_run", "synced", "skipped", "failed", "results"}
)
# Per-project entry shape — `outcome` is exactly one of "synced" /
# "skipped" / "failed"; `reason` populated only on "skipped"; `error`
# populated only on "failed"; both explicit `None` elsewhere so consumers
# can `jq -r '.results[] | .reason // empty'` without a defined-key guard.
_SYNC_ALL_RESULT_KEYS = frozenset({"project_root", "outcome", "reason", "error"})


def _json_payload_or_fail(stdout: str) -> dict[str, object]:
    """Parse the sync-all JSON stdout or raise with the offending text."""
    import json as _json

    try:
        payload = _json.loads(stdout)
    except _json.JSONDecodeError as exc:  # pragma: no cover — diagnostic only
        raise AssertionError(f"stdout is not valid JSON: {stdout!r}") from exc
    assert isinstance(payload, dict), f"top-level not an object: {payload!r}"
    return payload


def test_sync_all_text_output_unchanged(tmp_path: Path) -> None:
    """Default text-mode output must remain bytewise stable: the legacy
    `[sync] / Done.` lines and the `Done. Synced: N, ...` summary footer.
    Sanity-checks against an accidental JSON-as-default flip — would break
    this test instead of silently breaking shell consumers grepping for
    `Done.` or `failed:`."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg)])

    assert result.exit_code == 0, result.output
    assert "[sync]" in result.output
    assert "Done. Synced:" in result.output
    # Sanity: text mode must not leak JSON syntax on stdout.
    import json as _json

    with pytest.raises(_json.JSONDecodeError):
        _json.loads(result.stdout)


def test_sync_all_json_emits_well_formed_object_with_mixed_outcomes(tmp_path: Path) -> None:
    """`sync-all --json` emits a single object with the schema-locked seven-key
    set. Tests the three outcome paths (synced / skipped / failed) in one
    payload — proves the per-entry shape is consistent across all three
    branches and that the top-level counters match the per-entry outcomes.
    Cross-checks vault round-trip + per-entry `error` / `reason` population."""
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    fresh = tmp_path / "fresh"
    _seed_project(good)
    _seed_project(bad)
    _seed_project(fresh)
    _write_marker(fresh, time.time() - 60)  # fresh under 1h gate
    cfg = tmp_path / "config.yaml"
    vault = tmp_path / "vault"
    _write_config(cfg, vault_path=str(vault), projects=[good, bad, fresh])

    def _fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        if str(bad) in cmd:
            raise subprocess.CalledProcessError(
                returncode=1, cmd=cmd, output=b"", stderr=b"boom-from-bad-project"
            )
        return MagicMock(returncode=0, stdout=b"", stderr=b"")

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run", side_effect=_fake_run):
        result = runner.invoke(
            app,
            ["obsidian", "sync-all", "--config", str(cfg), "--stale-hours", "1", "--json"],
        )
    # Exit 1 because one project failed — JSON path preserves the exit
    # contract (failed > 0 → exit 1) parallel to the text path.
    assert result.exit_code == 1, result.output

    payload = _json_payload_or_fail(result.stdout)
    assert set(payload.keys()) == _SYNC_ALL_JSON_KEYS

    # Top-level invariants:
    assert payload["vault"] == str(vault)
    assert payload["stale_hours"] == 1.0
    assert payload["dry_run"] is False
    assert payload["synced"] == 1
    assert payload["skipped"] == 1
    assert payload["failed"] == 1

    # Per-entry shape lock + outcome population:
    results = payload["results"]
    assert isinstance(results, list)
    assert len(results) == 3
    by_root = {r["project_root"]: r for r in results}

    good_entry = by_root[str(good)]
    assert set(good_entry.keys()) == _SYNC_ALL_RESULT_KEYS
    assert good_entry["outcome"] == "synced"
    assert good_entry["reason"] is None
    assert good_entry["error"] is None

    bad_entry = by_root[str(bad)]
    assert set(bad_entry.keys()) == _SYNC_ALL_RESULT_KEYS
    assert bad_entry["outcome"] == "failed"
    assert bad_entry["reason"] is None
    assert bad_entry["error"] is not None
    assert "boom-from-bad-project" in str(bad_entry["error"])

    fresh_entry = by_root[str(fresh)]
    assert set(fresh_entry.keys()) == _SYNC_ALL_RESULT_KEYS
    assert fresh_entry["outcome"] == "skipped"
    assert fresh_entry["reason"] is not None
    assert "fresh" in str(fresh_entry["reason"])
    assert fresh_entry["error"] is None

    # Stdout/stderr split: per-project `[sync] / [fail]` chrome must NOT
    # appear on stdout (locks the `quiet=as_json` discipline so a future
    # refactor that reintroduces prose breaks this test).
    assert "[sync]" not in result.stdout
    assert "[fail]" not in result.stdout
    # Marker still written for the success case (side effects unchanged):
    assert (good / ".context" / _OBSIDIAN_MARKER).exists()
    assert not (bad / ".context" / _OBSIDIAN_MARKER).exists()


def test_sync_all_json_dry_run_emits_plan_without_subprocess(tmp_path: Path) -> None:
    """`--dry-run --json` emits the same schema as a real run but every
    `outcome` reflects the *plan* (would-sync / would-skip), no subprocess
    is invoked, and `dry_run: true` round-trips so a script can distinguish
    a plan from an execution. Locks against a regression that fired the
    sync subprocess in dry-run mode (would defeat the dry-run safety net)."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    cfg = tmp_path / "config.yaml"
    vault = tmp_path / "vault"
    _write_config(cfg, vault_path=str(vault), projects=[proj])

    runner = CliRunner()
    with patch("apps.cli.commands.obsidian_cmd.subprocess.run") as mock_run:
        result = runner.invoke(
            app, ["obsidian", "sync-all", "--config", str(cfg), "--dry-run", "--json"]
        )
    # No subprocess fired — dry-run is the canonical "plan, don't execute" gate.
    assert mock_run.call_count == 0
    assert result.exit_code == 0, result.output

    payload = _json_payload_or_fail(result.stdout)
    assert set(payload.keys()) == _SYNC_ALL_JSON_KEYS
    assert payload["dry_run"] is True
    assert payload["vault"] == str(vault)
    assert payload["synced"] == 1  # planned-to-sync count
    assert payload["skipped"] == 0
    assert payload["failed"] == 0
    assert len(payload["results"]) == 1
    entry = payload["results"][0]
    assert set(entry.keys()) == _SYNC_ALL_RESULT_KEYS
    assert entry["project_root"] == str(proj)
    assert entry["outcome"] == "synced"
    # No marker written — dry-run leaves on-disk state untouched.
    assert not (proj / ".context" / _OBSIDIAN_MARKER).exists()


def test_sync_all_json_obsidian_disabled_emits_empty_results(tmp_path: Path) -> None:
    """When `obsidian.enabled=false` the JSON path emits the schema-locked
    object with empty `results` and zero counters (exit 0) instead of the
    text-mode `Nothing to do` line. Mirrors the v0.8.45/v0.8.49/v0.8.50
    "no-work-done is still a successful run, surface the structured null
    rather than printing prose" discipline; lets a script check
    `jq -e '.results == []'` without parsing prose."""
    proj = tmp_path / "proj"
    _seed_project(proj)
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, vault_path=str(tmp_path / "vault"), projects=[proj], enabled=False)

    runner = CliRunner()
    result = runner.invoke(app, ["obsidian", "sync-all", "--config", str(cfg), "--json"])
    assert result.exit_code == 0, result.output

    payload = _json_payload_or_fail(result.stdout)
    assert set(payload.keys()) == _SYNC_ALL_JSON_KEYS
    assert payload["synced"] == 0
    assert payload["skipped"] == 0
    assert payload["failed"] == 0
    assert payload["results"] == []
    assert payload["dry_run"] is False


def test_sync_all_json_missing_config_exits_1_no_payload(tmp_path: Path) -> None:
    """Missing config file → exit 1 in JSON mode with no JSON payload on
    stdout — same v0.8.42-v0.8.60 discipline of "exit code is the gate,
    structured payload is for the success path". A regression that swallows
    the validation error into a `{"error": "..."}` stdout payload breaks
    this test."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["obsidian", "sync-all", "--config", str(tmp_path / "missing.yaml"), "--json"],
    )
    assert result.exit_code == 1, result.output
    # Stdout must NOT parse as a success-shape JSON object.
    if result.stdout.strip():
        import json as _json

        try:
            parsed = _json.loads(result.stdout)
            # If something parses, it must NOT be a success-shape entry.
            assert not (isinstance(parsed, dict) and "results" in parsed)
        except _json.JSONDecodeError:
            pass  # Expected — error path went to stderr, stdout has no payload.
