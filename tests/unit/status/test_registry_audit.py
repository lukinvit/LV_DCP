"""Unit tests for libs.status.registry_audit (v0.8.32).

Covers per-entry classification, activity counters, staleness heuristic,
and the never-scanned edge case.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml
from libs.status.registry_audit import (
    audit_registry,
    backup_status,
    is_missing,
    is_stale,
    iso_utc,
)


def _seed_cache(root: Path, *, packs: list[float]) -> None:
    """Create `.context/cache.db` with retrieval_traces rows at given epochs."""
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    db = ctx / "cache.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE retrieval_traces ("
        "trace_id TEXT, timestamp REAL, mode TEXT, coverage TEXT, trace_json TEXT)"
    )
    for i, ts in enumerate(packs):
        conn.execute(
            "INSERT INTO retrieval_traces VALUES (?, ?, ?, ?, ?)",
            (f"t{i}", ts, "navigate", "high", json.dumps({"final_ranking": [1]})),
        )
    conn.commit()
    conn.close()


def _write_cfg(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"projects": entries}), encoding="utf-8")
    return cfg


def test_audit_classifies_real_and_transient(tmp_path: Path) -> None:
    now = 1_800_000_000.0  # fixed clock for determinism
    real = tmp_path / "X5_BM"
    transient = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.32-abc"
    _seed_cache(real, packs=[now - 3600])  # 1h ago → counts as 7d
    _seed_cache(transient, packs=[])

    cfg = _write_cfg(
        tmp_path,
        [
            {"root": str(real), "registered_at_iso": iso_utc(now - 86400)},
            {"root": str(transient), "registered_at_iso": iso_utc(now - 86400)},
        ],
    )
    rows = audit_registry(cfg, now=now)

    assert len(rows) == 2
    by_name = {r.name: r for r in rows}
    assert by_name["X5_BM"].kind == "real"
    assert by_name["X5_BM"].scanned is True
    assert by_name["X5_BM"].packs_7d == 1
    assert by_name["X5_BM"].packs_total == 1
    assert by_name["v0.8.32-abc"].kind == "transient"
    assert by_name["v0.8.32-abc"].packs_7d == 0


def test_audit_never_scanned_project_has_no_cache(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    root = tmp_path / "unscanned"
    root.mkdir()
    cfg = _write_cfg(
        tmp_path,
        [{"root": str(root), "registered_at_iso": iso_utc(now - 3600)}],
    )
    rows = audit_registry(cfg, now=now)
    assert rows[0].scanned is False
    assert rows[0].packs_total == 0


def test_audit_computes_last_scan_age_hours(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    root = tmp_path / "p"
    root.mkdir()
    scan_ts = now - 5 * 3600  # 5 hours ago
    cfg = _write_cfg(
        tmp_path,
        [
            {
                "root": str(root),
                "registered_at_iso": iso_utc(now - 86400),
                "last_scan_at_iso": iso_utc(scan_ts),
            }
        ],
    )
    rows = audit_registry(cfg, now=now)
    assert rows[0].last_scan_age_hours is not None
    assert 4.9 < rows[0].last_scan_age_hours < 5.1


def test_is_stale_catches_zero_packs_and_old_scan(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    root = tmp_path / "dead_worktree"
    root.mkdir()
    scan_ts = now - 40 * 86400  # 40 days ago
    cfg = _write_cfg(
        tmp_path,
        [
            {
                "root": str(root),
                "registered_at_iso": iso_utc(scan_ts),
                "last_scan_at_iso": iso_utc(scan_ts),
            }
        ],
    )
    rows = audit_registry(cfg, now=now)
    assert is_stale(rows[0]) is True


def test_is_stale_skips_recently_used_entry(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    root = tmp_path / "active"
    _seed_cache(root, packs=[now - 3600])  # has a recent pack
    cfg = _write_cfg(
        tmp_path,
        [{"root": str(root), "registered_at_iso": iso_utc(now - 86400)}],
    )
    rows = audit_registry(cfg, now=now)
    assert is_stale(rows[0]) is False


def test_is_stale_treats_never_scanned_as_stale(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    root = tmp_path / "never"
    root.mkdir()
    cfg = _write_cfg(
        tmp_path,
        [{"root": str(root), "registered_at_iso": iso_utc(now - 10 * 86400)}],
    )
    rows = audit_registry(cfg, now=now)
    # Never scanned, zero packs — is_stale should return True so --stale surfaces it.
    assert is_stale(rows[0]) is True


# ---- missing predicate (v0.8.37) ------------------------------------------


def test_audit_marks_absent_root_as_missing(tmp_path: Path) -> None:
    """An entry whose root no longer exists on disk gets missing=True."""
    now = 1_800_000_000.0
    alive = tmp_path / "alive"
    alive.mkdir()
    deleted = tmp_path / "deleted_worktree"  # deliberately not created
    cfg = _write_cfg(
        tmp_path,
        [
            {"root": str(alive), "registered_at_iso": iso_utc(now - 3600)},
            {"root": str(deleted), "registered_at_iso": iso_utc(now - 3600)},
        ],
    )
    rows = audit_registry(cfg, now=now)
    by_name = {r.name: r for r in rows}
    assert by_name["alive"].missing is False
    assert by_name["deleted_worktree"].missing is True


def test_audit_missing_row_has_no_scan_signal(tmp_path: Path) -> None:
    """A tombstone row must report scanned=False — the cache-db probe is
    short-circuited so we never stat inside a deleted directory's parent."""
    now = 1_800_000_000.0
    deleted = tmp_path / "gone"
    cfg = _write_cfg(
        tmp_path,
        [{"root": str(deleted), "registered_at_iso": iso_utc(now - 3600)}],
    )
    rows = audit_registry(cfg, now=now)
    assert rows[0].missing is True
    assert rows[0].scanned is False
    assert rows[0].packs_total == 0
    assert rows[0].packs_7d == 0


def test_is_missing_returns_the_flag(tmp_path: Path) -> None:
    """`is_missing` mirrors the `is_stale` helper shape — returns the
    predicate boolean, stays trivial, doesn't re-probe the filesystem."""
    now = 1_800_000_000.0
    alive = tmp_path / "here"
    alive.mkdir()
    deleted = tmp_path / "poof"
    cfg = _write_cfg(
        tmp_path,
        [
            {"root": str(alive), "registered_at_iso": iso_utc(now - 3600)},
            {"root": str(deleted), "registered_at_iso": iso_utc(now - 3600)},
        ],
    )
    rows = audit_registry(cfg, now=now)
    by_name = {r.name: r for r in rows}
    assert is_missing(by_name["here"]) is False
    assert is_missing(by_name["poof"]) is True


def test_missing_and_stale_are_independent_predicates(tmp_path: Path) -> None:
    """A tombstone registered this morning is missing but not stale; a dead
    worktree registered 40 days ago is both missing AND stale."""
    now = 1_800_000_000.0
    recent_tombstone = tmp_path / "recent_gone"  # never created
    ancient_tombstone = tmp_path / "ancient_gone"  # never created
    cfg = _write_cfg(
        tmp_path,
        [
            {
                "root": str(recent_tombstone),
                "registered_at_iso": iso_utc(now - 3600),
                "last_scan_at_iso": iso_utc(now - 1800),
            },
            {
                "root": str(ancient_tombstone),
                "registered_at_iso": iso_utc(now - 40 * 86400),
                "last_scan_at_iso": iso_utc(now - 40 * 86400),
            },
        ],
    )
    rows = audit_registry(cfg, now=now)
    by_name = {r.name: r for r in rows}
    # Recent tombstone: missing, but scan_age=30min → is_stale is False
    # because packs_total=0 yet age<30d… wait: packs_total=0 AND
    # last_scan_age_hours=0.5 → 0.5 < 720 → not stale. ✅
    assert is_missing(by_name["recent_gone"]) is True
    assert is_stale(by_name["recent_gone"]) is False
    # Ancient tombstone: missing AND stale (40d > 30d, packs_total=0).
    assert is_missing(by_name["ancient_gone"]) is True
    assert is_stale(by_name["ancient_gone"]) is True


# ---- v0.8.41: backup_status (prune-undo discoverability) -------------------


def test_backup_status_returns_none_when_no_bak(tmp_path: Path) -> None:
    """Pure read: missing `*.bak` yields ``(None, None)``, not an exception.

    The footer renderer needs a cheap "is there a backup?" check that
    doesn't raise — `ls` is a hot path that runs even when the user has
    never invoked `prune --yes`.
    """
    cfg = _write_cfg(tmp_path, [])

    backup_path, age_seconds = backup_status(cfg)

    assert backup_path is None
    assert age_seconds is None


def test_backup_status_returns_path_and_age_when_bak_exists(tmp_path: Path) -> None:
    """Backup present: returns its absolute path and a non-negative age.

    Age is mtime-delta from the injected ``now`` clock, allowing
    deterministic tests without sleeping.
    """
    now = 1_800_000_000.0
    cfg = _write_cfg(tmp_path, [])
    bak = cfg.with_name(cfg.name + ".bak")
    bak.write_text("projects: []\n", encoding="utf-8")
    # Forge mtime to a known epoch so the age math is deterministic.
    import os

    os.utime(bak, (now - 7200, now - 7200))  # 2 hours ago

    backup_path, age_seconds = backup_status(cfg, now=now)

    assert backup_path == bak
    assert age_seconds is not None
    assert 7199.0 <= age_seconds <= 7201.0  # ~2h, allow filesystem rounding


def test_backup_status_clamps_negative_age_to_zero(tmp_path: Path) -> None:
    """Clock-skew safety: a future-dated backup mtime returns age 0, not negative.

    On systems with clock drift between the file mtime source and
    ``time.time()`` (e.g., NFS, dual-boot, virtualization), the delta can
    transiently go negative. The footer formatter rounds to "<1h" anyway,
    but the contract is non-negative seconds for downstream consumers.
    """
    now = 1_800_000_000.0
    cfg = _write_cfg(tmp_path, [])
    bak = cfg.with_name(cfg.name + ".bak")
    bak.write_text("projects: []\n", encoding="utf-8")
    import os

    os.utime(bak, (now + 60, now + 60))  # 1 minute in the future

    _, age_seconds = backup_status(cfg, now=now)

    assert age_seconds == 0.0


def test_backup_status_respects_custom_suffix(tmp_path: Path) -> None:
    """``backup_suffix`` kwarg lets tests / future flags target a non-default sidecar.

    Default is ``.bak`` (matches `prune_stale` / `restore_from_backup`),
    but exposing the kwarg keeps the door open for a future
    ``--backup-suffix`` flag without a library signature change.
    """
    cfg = _write_cfg(tmp_path, [])
    custom_bak = cfg.with_name(cfg.name + ".saved")
    custom_bak.write_text("projects: []\n", encoding="utf-8")

    # Default suffix → no backup
    default_path, _ = backup_status(cfg)
    assert default_path is None

    # Custom suffix → finds the saved file
    custom_path, _ = backup_status(cfg, backup_suffix=".saved")
    assert custom_path == custom_bak
