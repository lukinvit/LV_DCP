"""Unit tests for libs.status.value_metrics.

Covers v0.8.31 transient-project classification: `.claude/worktrees/*`
ship-ceremony artifacts and `sample_repo` test fixtures must be separated
from real user projects in the dashboard adoption counters.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import yaml
from libs.status.value_metrics import _is_transient, collect_value_metrics


def test_is_transient_detects_worktree_segments(tmp_path: Path) -> None:
    root = tmp_path / "repo" / ".claude" / "worktrees" / "v0.8.31-abc"
    assert _is_transient(root) is True


def test_is_transient_detects_sample_repo_fixture(tmp_path: Path) -> None:
    root = tmp_path / "tests" / "fixtures" / "sample_repo"
    assert _is_transient(root) is True


def test_is_transient_rejects_normal_project(tmp_path: Path) -> None:
    root = tmp_path / "Nextcloud" / "projects" / "X5_BM"
    assert _is_transient(root) is False


def test_is_transient_rejects_unrelated_claude_path(tmp_path: Path) -> None:
    # `.claude/` without a following `worktrees/` segment is just a config dir.
    root = tmp_path / "project" / ".claude" / "hooks"
    assert _is_transient(root) is False


def _seed_project(root: Path, *, packs: int = 0, transient: bool = False) -> Path:
    """Create a minimal `.context/cache.db` with `packs` retrieval traces."""
    ctx = root / ".context"
    ctx.mkdir(parents=True, exist_ok=True)
    db = ctx / "cache.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (path TEXT PRIMARY KEY, language TEXT, size_bytes INTEGER)")
    conn.execute("CREATE TABLE symbols (file_path TEXT, name TEXT)")
    conn.execute("CREATE TABLE relations (src TEXT, dst TEXT, relation_type TEXT)")
    conn.execute(
        "CREATE TABLE retrieval_traces ("
        "trace_id TEXT, timestamp REAL, mode TEXT, coverage TEXT, trace_json TEXT)"
    )
    now = time.time()
    for i in range(packs):
        conn.execute(
            "INSERT INTO retrieval_traces VALUES (?, ?, ?, ?, ?)",
            (f"t{i}", now, "navigate", "high", json.dumps({"final_ranking": [1, 2]})),
        )
    conn.commit()
    conn.close()
    return db


def _write_config(tmp_path: Path, roots: list[Path]) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {
                        "root": str(r),
                        "registered_at_iso": "2026-04-24T00:00:00Z",
                    }
                    for r in roots
                ]
            }
        ),
        encoding="utf-8",
    )
    return cfg


def test_collect_value_metrics_separates_real_and_transient(tmp_path: Path) -> None:
    real_active = tmp_path / "X5_BM"
    real_dormant = tmp_path / "LV_Presentation"
    worktree = tmp_path / "LV_DCP" / ".claude" / "worktrees" / "v0.8.31-xyz"
    fixture = tmp_path / "tests" / "fixtures" / "sample_repo"

    _seed_project(real_active, packs=5)
    _seed_project(real_dormant, packs=0)
    _seed_project(worktree, packs=2)
    _seed_project(fixture, packs=3)

    config = _write_config(tmp_path, [real_active, real_dormant, worktree, fixture])
    m = collect_value_metrics(config)

    # Total (backward compatible) counts everything
    assert m.projects_total == 4
    assert m.projects_active == 3  # real_active + worktree + fixture served packs

    # Real vs transient split is the honest signal
    assert m.projects_real_total == 2
    assert m.projects_real_active == 1  # only X5_BM
    assert m.projects_transient_total == 2
    assert m.projects_transient_active == 2


def test_collect_value_metrics_zero_transient_when_none_registered(tmp_path: Path) -> None:
    real_one = tmp_path / "project_a"
    real_two = tmp_path / "project_b"
    _seed_project(real_one, packs=1)
    _seed_project(real_two, packs=0)

    config = _write_config(tmp_path, [real_one, real_two])
    m = collect_value_metrics(config)

    assert m.projects_transient_total == 0
    assert m.projects_transient_active == 0
    assert m.projects_real_total == 2
    assert m.projects_real_active == 1
