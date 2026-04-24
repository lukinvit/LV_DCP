"""Tests for the `ctx registry` CLI group (v0.8.32 ls, v0.8.33 prune)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
import yaml
from apps.cli.main import app
from typer.testing import CliRunner


def _seed_cache(root: Path) -> None:
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    db = ctx / "cache.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE retrieval_traces ("
        "trace_id TEXT, timestamp REAL, mode TEXT, coverage TEXT, trace_json TEXT)"
    )
    conn.execute(
        "INSERT INTO retrieval_traces VALUES (?, ?, ?, ?, ?)",
        ("t0", time.time(), "navigate", "high", "{}"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    real = tmp_path / "X5_BM"
    transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.32-abc"
    _seed_cache(real)
    transient.mkdir(parents=True)
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {"root": str(real), "registered_at_iso": "2026-04-24T00:00:00Z"},
                    {"root": str(transient), "registered_at_iso": "2026-04-24T00:00:00Z"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(path))
    return path


def test_registry_ls_text_default(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls"])
    assert result.exit_code == 0, result.stdout
    assert "X5_BM" in result.stdout
    assert "v0.8.32-abc" in result.stdout
    assert "real" in result.stdout
    assert "transient" in result.stdout


def test_registry_ls_json_shape(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    kinds = {row["kind"] for row in payload}
    assert kinds == {"real", "transient"}
    for row in payload:
        for key in ("name", "root", "kind", "scanned", "packs_7d", "packs_total"):
            assert key in row


def test_registry_ls_kind_filter_real(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--kind", "real", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["kind"] == "real"


def test_registry_ls_kind_filter_transient(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--kind", "transient", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["kind"] == "transient"


def test_registry_ls_rejects_invalid_kind(cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "ls", "--kind", "bogus"])
    assert result.exit_code == 2
    assert "must be 'real', 'transient', or 'all'" in result.stdout or "must be" in (
        result.stderr or ""
    )


def test_registry_ls_stale_surfaces_dormant_entries(cfg: Path) -> None:
    # The transient `v0.8.32-abc` has zero packs and was registered "today"
    # in the fixture, but its `.context/cache.db` is absent → never scanned
    # path → is_stale=True (never-scanned branch).
    result = CliRunner().invoke(app, ["registry", "ls", "--stale", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    names = {row["name"] for row in payload}
    assert "v0.8.32-abc" in names
    # X5_BM has 1 pack → NOT stale.
    assert "X5_BM" not in names


# ---- prune (v0.8.33) -------------------------------------------------------


@pytest.fixture
def stale_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A registry with one fresh real project and one stale transient one."""
    real = tmp_path / "X5_BM"
    _seed_cache(real)
    stale_transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.30-old"
    stale_transient.mkdir(parents=True)  # no cache.db → never scanned

    path = tmp_path / "config.yaml"
    # 60 days ago so it trips the 30d default cutoff on the never-scanned branch.
    old_iso = "2026-02-23T00:00:00Z"
    recent_iso = "2026-04-24T00:00:00Z"
    path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {"root": str(real), "registered_at_iso": recent_iso},
                    {"root": str(stale_transient), "registered_at_iso": old_iso},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(path))
    return path


def test_registry_prune_dry_run_is_default(stale_cfg: Path) -> None:
    original = stale_cfg.read_bytes()
    result = CliRunner().invoke(app, ["registry", "prune"])
    assert result.exit_code == 0, result.stdout
    assert "dry-run" in result.stdout
    assert "v0.8.30-old" in result.stdout
    # Config untouched, no backup written.
    assert stale_cfg.read_bytes() == original
    assert not stale_cfg.with_name(stale_cfg.name + ".bak").exists()


def test_registry_prune_yes_applies_and_writes_backup(stale_cfg: Path) -> None:
    original = stale_cfg.read_bytes()
    result = CliRunner().invoke(app, ["registry", "prune", "--yes"])
    assert result.exit_code == 0, result.stdout
    assert "REMOVED" in result.stdout
    assert "backup saved" in result.stdout

    backup = stale_cfg.with_name(stale_cfg.name + ".bak")
    assert backup.exists()
    assert backup.read_bytes() == original

    payload = yaml.safe_load(stale_cfg.read_text(encoding="utf-8"))
    roots = [p["root"] for p in payload["projects"]]
    assert len(roots) == 1
    assert "v0.8.30-old" not in " ".join(roots)


def test_registry_prune_rejects_bad_kind(stale_cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "prune", "--kind", "bogus"])
    assert result.exit_code == 2
    assert "must be" in (result.stdout + (result.stderr or ""))


def test_registry_prune_rejects_nonpositive_older_than(stale_cfg: Path) -> None:
    result = CliRunner().invoke(app, ["registry", "prune", "--older-than", "0"])
    assert result.exit_code == 2


def test_registry_prune_real_kind_spares_transient(stale_cfg: Path) -> None:
    # The stale entry in the fixture is a transient worktree. --kind real
    # should find no candidates and report nothing to do.
    result = CliRunner().invoke(app, ["registry", "prune", "--kind", "real"])
    assert result.exit_code == 0
    assert "nothing to do" in result.stdout


# ---- --missing (v0.8.36) --------------------------------------------------


@pytest.fixture
def missing_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A registry with one alive project and one whose root was deleted."""
    alive = tmp_path / "AliveProject"
    _seed_cache(alive)
    deleted = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "deleted-today"
    # deliberately NOT created — simulates `git worktree remove` aftermath

    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {"root": str(alive), "registered_at_iso": "2026-04-24T00:00:00Z"},
                    {
                        "root": str(deleted),
                        "registered_at_iso": "2026-04-25T00:00:00Z",
                        "last_scan_at_iso": "2026-04-25T09:00:00Z",  # recent → not stale-by-age
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(path))
    return path


def test_registry_prune_missing_dry_run_lists_deleted_root(missing_cfg: Path) -> None:
    """`ctx registry prune --missing` (no --yes) previews deleted roots
    and leaves the config untouched.
    """
    original = missing_cfg.read_bytes()
    result = CliRunner().invoke(app, ["registry", "prune", "--missing"])
    assert result.exit_code == 0, result.stdout
    assert "missing root" in result.stdout
    assert "deleted-today" in result.stdout
    assert "dry-run" in result.stdout
    # Untouched.
    assert missing_cfg.read_bytes() == original
    assert not missing_cfg.with_name(missing_cfg.name + ".bak").exists()


def test_registry_prune_missing_yes_removes_and_backs_up(missing_cfg: Path) -> None:
    """`--missing --yes` removes the tombstone and writes the *.bak sidecar."""
    original = missing_cfg.read_bytes()
    result = CliRunner().invoke(app, ["registry", "prune", "--missing", "--yes"])
    assert result.exit_code == 0, result.stdout
    assert "REMOVED" in result.stdout
    assert "backup saved" in result.stdout

    backup = missing_cfg.with_name(missing_cfg.name + ".bak")
    assert backup.exists()
    assert backup.read_bytes() == original

    payload = yaml.safe_load(missing_cfg.read_text(encoding="utf-8"))
    roots = [p["root"] for p in payload["projects"]]
    assert len(roots) == 1
    assert "AliveProject" in roots[0]


def test_registry_prune_missing_nothing_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When every root exists on disk, --missing is a graceful no-op."""
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {"root": str(a), "registered_at_iso": "2026-04-25T00:00:00Z"},
                    {"root": str(b), "registered_at_iso": "2026-04-25T00:00:00Z"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(path))

    result = CliRunner().invoke(app, ["registry", "prune", "--missing"])
    assert result.exit_code == 0, result.stdout
    assert "nothing to do" in result.stdout
    assert "missing root" in result.stdout


# ---- ls --missing (v0.8.37) ----------------------------------------------


def test_registry_ls_missing_filters_to_tombstones(missing_cfg: Path) -> None:
    """`ctx registry ls --missing --json` returns only the deleted-root row."""
    result = CliRunner().invoke(app, ["registry", "ls", "--missing", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert "deleted-today" in payload[0]["root"]
    assert payload[0]["missing"] is True


def test_registry_ls_missing_text_shows_MISS_marker(missing_cfg: Path) -> None:
    """The text table surfaces tombstones in the SCAN column as `MISS`."""
    result = CliRunner().invoke(app, ["registry", "ls", "--missing"])
    assert result.exit_code == 0, result.stdout
    assert "deleted-today" in result.stdout
    assert "MISS" in result.stdout


def test_registry_ls_missing_composes_with_kind(missing_cfg: Path) -> None:
    """`--missing` AND `--kind` compose: transient tombstone shows up;
    real tombstone (if any) is filtered out when --kind transient."""
    result = CliRunner().invoke(
        app, ["registry", "ls", "--missing", "--kind", "transient", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # The missing_cfg fixture's deleted entry lives under .claude/worktrees/ → transient.
    assert len(payload) == 1
    assert payload[0]["kind"] == "transient"
    assert payload[0]["missing"] is True


def test_registry_ls_missing_empty_when_all_roots_exist(cfg: Path) -> None:
    """When every registered root exists, `ls --missing` returns nothing."""
    result = CliRunner().invoke(app, ["registry", "ls", "--missing", "--json"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == []


def test_registry_ls_json_carries_missing_field(cfg: Path) -> None:
    """Every row in `ls --json` carries the new `missing` boolean field."""
    result = CliRunner().invoke(app, ["registry", "ls", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    for row in payload:
        assert "missing" in row
        # All fixture paths exist on disk in the `cfg` fixture.
        assert row["missing"] is False


# ---- prune --json (v0.8.38) ----------------------------------------------


_PRUNE_JSON_KEYS = {"kept", "removed", "applied", "backup_path", "config_path"}


def test_registry_prune_json_dry_run_shape(stale_cfg: Path) -> None:
    """`prune --json` (no --yes) emits a parseable preview with applied=False
    and backup_path=None. Schema mirrors PruneResult."""
    original = stale_cfg.read_bytes()
    result = CliRunner().invoke(app, ["registry", "prune", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == _PRUNE_JSON_KEYS
    assert payload["applied"] is False
    assert payload["backup_path"] is None
    assert payload["config_path"] == str(stale_cfg)
    # The fixture's stale transient worktree is the candidate.
    assert any("v0.8.30-old" in r for r in payload["removed"])
    # Config untouched and no backup written.
    assert stale_cfg.read_bytes() == original
    assert not stale_cfg.with_name(stale_cfg.name + ".bak").exists()


def test_registry_prune_json_yes_applies_and_reports_backup(stale_cfg: Path) -> None:
    """`prune --json --yes` mutates and returns a JSON object with
    applied=True and backup_path populated."""
    result = CliRunner().invoke(app, ["registry", "prune", "--json", "--yes"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["applied"] is True
    assert payload["backup_path"] == str(stale_cfg.with_name(stale_cfg.name + ".bak"))
    assert payload["config_path"] == str(stale_cfg)
    assert len(payload["removed"]) >= 1
    # The kept list reflects the post-mutation registry state.
    survivors = yaml.safe_load(stale_cfg.read_text(encoding="utf-8"))["projects"]
    assert payload["kept"] == [p["root"] for p in survivors]


def test_registry_prune_json_nothing_to_do_returns_empty_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the policy matches no candidates, `prune --json` still emits a
    well-formed object with `removed: []` and `applied: false`."""
    a = tmp_path / "A"
    a.mkdir()
    _seed_cache(a)  # has packs → not stale → no candidates under default policy
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"projects": [{"root": str(a), "registered_at_iso": "2026-04-25T00:00:00Z"}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_CONFIG_PATH", str(cfg_path))

    result = CliRunner().invoke(app, ["registry", "prune", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["removed"] == []
    assert payload["applied"] is False
    assert payload["backup_path"] is None
    assert payload["kept"] == [str(a)]


def test_registry_prune_json_missing_dry_run_lists_tombstones(missing_cfg: Path) -> None:
    """`prune --missing --json` (no --yes) returns the tombstone list as JSON
    without mutating the config."""
    original = missing_cfg.read_bytes()
    result = CliRunner().invoke(app, ["registry", "prune", "--missing", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["applied"] is False
    assert payload["backup_path"] is None
    assert any("deleted-today" in r for r in payload["removed"])
    # Untouched.
    assert missing_cfg.read_bytes() == original


def test_registry_prune_json_suppresses_human_hint_text(stale_cfg: Path) -> None:
    """JSON mode emits pure data — no `dry-run` hint, no `nothing to do`,
    no `REMOVED` header. Output must be a single parseable JSON object."""
    result = CliRunner().invoke(app, ["registry", "prune", "--json"])
    assert result.exit_code == 0, result.stdout
    # Every line of stdout belongs to the JSON payload — `json.loads` would
    # raise on any trailing hint text.
    json.loads(result.stdout)
    assert "dry-run" not in result.stdout
    assert "Pass --yes" not in result.stdout
    assert "REMOVED" not in result.stdout
    assert "nothing to do" not in result.stdout
