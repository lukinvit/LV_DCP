"""Tests for breadcrumb TTL + LRU pruning."""

from __future__ import annotations

import time
from pathlib import Path

from libs.breadcrumbs.prune import enforce_per_project_cap, prune_older_than
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_prune_older_than_removes_old_rows(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.connect().execute(
        "INSERT INTO breadcrumbs (project_root, timestamp, source, os_user, privacy_mode) "
        "VALUES (?, ?, 'pack', 'alice', 'local_only')",
        ("/x", 100.0),
    )
    s.connect().commit()
    write_pack_event(store=s, project_root="/x", os_user="alice", query="q", mode="navigate", paths_touched=[])
    deleted = prune_older_than(store=s, cutoff_ts=time.time() - 60)
    assert deleted == 1
    remaining = s.connect().execute("SELECT COUNT(*) FROM breadcrumbs").fetchone()[0]
    assert remaining == 1


def test_enforce_per_project_cap_drops_oldest(tmp_path: Path) -> None:
    s = _store(tmp_path)
    for i in range(15):
        write_pack_event(store=s, project_root="/x", os_user="alice", query=f"q{i}", mode="navigate", paths_touched=[])
    dropped = enforce_per_project_cap(store=s, project_root="/x", max_rows=10)
    assert dropped == 5
    remaining = s.connect().execute(
        "SELECT COUNT(*) FROM breadcrumbs WHERE project_root = ?", ("/x",)
    ).fetchone()[0]
    assert remaining == 10


def test_enforce_cap_no_op_when_under(tmp_path: Path) -> None:
    s = _store(tmp_path)
    for i in range(3):
        write_pack_event(store=s, project_root="/x", os_user="alice", query=f"q{i}", mode="navigate", paths_touched=[])
    dropped = enforce_per_project_cap(store=s, project_root="/x", max_rows=10)
    assert dropped == 0
