"""Unit tests for libs.status.registry_prune (v0.8.33).

Covers dry-run preview, the `--yes` gate, backup sidecar, kind and
older-than filters, and the `ValueError` contract for bad `kind`.

Safety contract under test:

- ``apply=False`` is a pure read — never writes the config, never
  writes the `*.bak` sidecar.
- ``apply=True`` writes the backup BEFORE mutating the config, so a
  partial failure still leaves a recoverable snapshot on disk.
- Only entries matching BOTH the kind filter AND the staleness cutoff
  are removed; everything else is preserved.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml
from libs.core.projects_config import load_config
from libs.status.registry_audit import iso_utc
from libs.status.registry_prune import plan_prune, prune_stale


def _seed_empty_cache(root: Path) -> None:
    """Create `.context/cache.db` with the traces table but zero rows."""
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ctx / "cache.db")
    conn.execute(
        "CREATE TABLE retrieval_traces ("
        "trace_id TEXT, timestamp REAL, mode TEXT, coverage TEXT, trace_json TEXT)"
    )
    conn.commit()
    conn.close()


def _seed_active_cache(root: Path, *, ts: float) -> None:
    """Create `.context/cache.db` with one retrieval trace."""
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ctx / "cache.db")
    conn.execute(
        "CREATE TABLE retrieval_traces ("
        "trace_id TEXT, timestamp REAL, mode TEXT, coverage TEXT, trace_json TEXT)"
    )
    conn.execute(
        "INSERT INTO retrieval_traces VALUES (?, ?, ?, ?, ?)",
        ("t0", ts, "navigate", "high", "{}"),
    )
    conn.commit()
    conn.close()


def _write_cfg(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(yaml.safe_dump({"projects": entries}), encoding="utf-8")


def test_plan_prune_lists_candidates_without_mutation(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    dead = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "old-branch"
    dead.mkdir(parents=True)
    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [{"root": str(dead), "registered_at_iso": iso_utc(now - 60 * 86400)}],
    )
    original_bytes = cfg.read_bytes()

    candidates = plan_prune(cfg, older_than_days=30, kind="transient")
    assert len(candidates) == 1
    assert candidates[0].root == str(dead)

    # The plan is pure — config is byte-identical afterwards.
    assert cfg.read_bytes() == original_bytes
    assert not cfg.with_name(cfg.name + ".bak").exists()


def test_prune_dry_run_is_noop(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    dead = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "x"
    dead.mkdir(parents=True)
    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [{"root": str(dead), "registered_at_iso": iso_utc(now - 60 * 86400)}],
    )
    original = cfg.read_bytes()

    result = prune_stale(cfg, older_than_days=30, kind="transient", apply=False)
    assert result.applied is False
    assert result.backup_path is None
    assert result.removed == [str(dead)]
    assert cfg.read_bytes() == original
    assert not cfg.with_name(cfg.name + ".bak").exists()


def test_prune_apply_removes_matching_and_writes_backup(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    keep = tmp_path / "X5_BM"
    _seed_active_cache(keep, ts=now - 3600)
    dead_transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.30-xyz"
    dead_transient.mkdir(parents=True)

    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {"root": str(keep), "registered_at_iso": iso_utc(now - 86400)},
            {
                "root": str(dead_transient),
                "registered_at_iso": iso_utc(now - 60 * 86400),
            },
        ],
    )
    original = cfg.read_bytes()

    result = prune_stale(cfg, older_than_days=30, kind="transient", apply=True)

    assert result.applied is True
    assert result.removed == [str(dead_transient)]
    assert result.kept == [str(keep)]
    assert result.backup_path is not None
    assert result.backup_path.exists()
    # Backup holds the pre-mutation bytes verbatim.
    assert result.backup_path.read_bytes() == original

    # Config now lists only the survivor.
    reloaded = load_config(cfg)
    assert [str(e.root) for e in reloaded.projects] == [str(keep)]


def test_prune_real_kind_does_not_touch_transient(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    dormant_real = tmp_path / "abandoned_project"
    dormant_real.mkdir()
    dormant_transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.30-xyz"
    dormant_transient.mkdir(parents=True)

    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {
                "root": str(dormant_real),
                "registered_at_iso": iso_utc(now - 60 * 86400),
            },
            {
                "root": str(dormant_transient),
                "registered_at_iso": iso_utc(now - 60 * 86400),
            },
        ],
    )

    result = prune_stale(cfg, older_than_days=30, kind="real", apply=True)
    assert result.removed == [str(dormant_real)]
    # The transient entry survives when kind filter is "real".
    reloaded = load_config(cfg)
    assert [str(e.root) for e in reloaded.projects] == [str(dormant_transient)]


def test_prune_all_kind_prunes_both_buckets(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    a = tmp_path / "abandoned"
    a.mkdir()
    b = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "zz"
    b.mkdir(parents=True)
    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {"root": str(a), "registered_at_iso": iso_utc(now - 60 * 86400)},
            {"root": str(b), "registered_at_iso": iso_utc(now - 60 * 86400)},
        ],
    )
    result = prune_stale(cfg, older_than_days=30, kind="all", apply=True)
    assert set(result.removed) == {str(a), str(b)}
    assert load_config(cfg).projects == []


def test_prune_respects_older_than_cutoff(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    recent = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "just-made"
    recent.mkdir(parents=True)
    cfg = tmp_path / "config.yaml"
    # Registered 5 days ago, no cache → is_stale treats never-scanned as stale.
    # But older_than_days=30 means last_scan_age None ≥ 30d is still True
    # (the is_stale helper short-circuits on None). To prove older_than
    # is respected, use an entry with a recent last_scan_at_iso.
    _write_cfg(
        cfg,
        [
            {
                "root": str(recent),
                "registered_at_iso": iso_utc(now - 5 * 86400),
                "last_scan_at_iso": iso_utc(now - 5 * 86400),
            }
        ],
    )

    result = prune_stale(cfg, older_than_days=30, kind="transient", apply=True)
    # 5d last scan < 30d cutoff → not pruned.
    assert result.removed == []
    assert result.applied is False  # no-removal short-circuit keeps applied=False
    assert result.backup_path is None


def test_prune_rejects_invalid_kind(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, [])
    with pytest.raises(ValueError, match="kind must be"):
        prune_stale(cfg, kind="bogus")


def test_prune_empty_registry_is_graceful(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, [])
    result = prune_stale(cfg, apply=True)
    assert result.removed == []
    assert result.applied is False
    assert result.backup_path is None


# ---- v0.8.36: --missing (root directory gone from disk) ------------------


def test_plan_prune_missing_lists_absent_roots(tmp_path: Path) -> None:
    """``missing_only=True`` catches entries whose root path is gone.

    Independent of ``kind`` / ``older_than_days`` — a deleted worktree or a
    moved project root leaves a tombstone entry that the staleness gate
    doesn't catch for 30 days. This predicate catches it immediately.
    """
    now = 1_800_000_000.0
    # deleted_root is referenced in the registry but never created on disk
    deleted_root = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.20-gone"
    # live_root exists and should survive
    live_root = tmp_path / "ActiveProject"
    live_root.mkdir()

    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {"root": str(deleted_root), "registered_at_iso": iso_utc(now - 86400)},
            {"root": str(live_root), "registered_at_iso": iso_utc(now - 86400)},
        ],
    )

    candidates = plan_prune(cfg, missing_only=True)

    assert len(candidates) == 1
    assert candidates[0].root == str(deleted_root)


def test_prune_missing_ignores_older_than_gate(tmp_path: Path) -> None:
    """Freshly-registered worktrees that get deleted same-day must be
    catchable by ``--missing`` even though they fail the 30-day gate.
    """
    now = 1_800_000_000.0
    deleted_root = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "just-shipped"
    # Registered a few hours ago, last scan a few hours ago — far from stale.
    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {
                "root": str(deleted_root),
                "registered_at_iso": iso_utc(now - 3600),
                "last_scan_at_iso": iso_utc(now - 1800),
            }
        ],
    )

    # The staleness-gated mode should NOT list it (not stale by age).
    staleness_candidates = plan_prune(cfg, older_than_days=30, kind="all")
    assert staleness_candidates == []

    # The missing-root mode SHOULD list it.
    missing_candidates = plan_prune(cfg, missing_only=True)
    assert len(missing_candidates) == 1
    assert missing_candidates[0].root == str(deleted_root)


def test_prune_missing_ignores_kind_filter(tmp_path: Path) -> None:
    """A gone-from-disk entry is pruned regardless of classification."""
    now = 1_800_000_000.0
    gone_real = tmp_path / "former_project"  # never created
    gone_transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "also-gone"  # never created

    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {"root": str(gone_real), "registered_at_iso": iso_utc(now - 86400)},
            {"root": str(gone_transient), "registered_at_iso": iso_utc(now - 86400)},
        ],
    )

    # Even with kind='transient' (the default), missing_only overrides and
    # catches the real-classified entry too.
    candidates = plan_prune(cfg, kind="transient", missing_only=True)
    assert {c.root for c in candidates} == {str(gone_real), str(gone_transient)}


def test_prune_missing_applies_with_backup(tmp_path: Path) -> None:
    """``apply=True`` on ``missing_only`` mutates and writes the backup."""
    now = 1_800_000_000.0
    alive = tmp_path / "Alive"
    alive.mkdir()
    dead = tmp_path / "Dead"  # never created

    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {"root": str(alive), "registered_at_iso": iso_utc(now - 86400)},
            {"root": str(dead), "registered_at_iso": iso_utc(now - 86400)},
        ],
    )
    original = cfg.read_bytes()

    result = prune_stale(cfg, missing_only=True, apply=True)

    assert result.applied is True
    assert result.removed == [str(dead)]
    assert result.kept == [str(alive)]
    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == original

    reloaded = load_config(cfg)
    assert [str(e.root) for e in reloaded.projects] == [str(alive)]


def test_prune_missing_no_candidates_is_graceful(tmp_path: Path) -> None:
    """When every registered root still exists, missing-mode is a no-op."""
    now = 1_800_000_000.0
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    cfg = tmp_path / "config.yaml"
    _write_cfg(
        cfg,
        [
            {"root": str(a), "registered_at_iso": iso_utc(now - 86400)},
            {"root": str(b), "registered_at_iso": iso_utc(now - 86400)},
        ],
    )

    result = prune_stale(cfg, missing_only=True, apply=True)
    assert result.removed == []
    assert result.applied is False
    assert result.backup_path is None
    assert [str(e.root) for e in load_config(cfg).projects] == [str(a), str(b)]
