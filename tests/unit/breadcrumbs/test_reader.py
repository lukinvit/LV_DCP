"""Tests for breadcrumb reader."""

from __future__ import annotations

import time
from pathlib import Path

from libs.breadcrumbs.reader import load_cross_project, load_recent
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_load_recent_filters_by_user(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/x",
        os_user="alice",
        query="q",
        mode="navigate",
        paths_touched=[],
    )
    write_pack_event(
        store=s,
        project_root="/x",
        os_user="bob",
        query="q",
        mode="navigate",
        paths_touched=[],
    )
    rows = load_recent(store=s, project_root="/x", os_user="alice", since_ts=0, limit=100)
    assert len(rows) == 1
    assert rows[0].os_user == "alice"


def test_load_recent_window(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/x",
        os_user="alice",
        query="q",
        mode="navigate",
        paths_touched=[],
    )
    cutoff = time.time() + 10  # future cutoff → nothing returned
    rows = load_recent(store=s, project_root="/x", os_user="alice", since_ts=cutoff, limit=100)
    assert rows == []


def test_load_recent_cc_account_filter(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/x",
        os_user="alice",
        query="q",
        mode="navigate",
        paths_touched=[],
        cc_account_email="alice@x.com",
    )
    write_pack_event(
        store=s,
        project_root="/x",
        os_user="alice",
        query="q",
        mode="navigate",
        paths_touched=[],
        cc_account_email="other@x.com",
    )
    rows = load_recent(
        store=s,
        project_root="/x",
        os_user="alice",
        since_ts=0,
        limit=100,
        cc_account_email="alice@x.com",
    )
    assert len(rows) == 1
    assert rows[0].cc_account_email == "alice@x.com"


def test_load_recent_cc_account_filter_includes_null(tmp_path: Path) -> None:
    """Null email rows must be visible to any current user (best-effort fallback)."""
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/x",
        os_user="alice",
        query="q",
        mode="navigate",
        paths_touched=[],
    )
    rows = load_recent(
        store=s,
        project_root="/x",
        os_user="alice",
        since_ts=0,
        limit=100,
        cc_account_email="alice@x.com",
    )
    assert len(rows) == 1


def test_load_cross_project_orders_by_recency(tmp_path: Path) -> None:
    s = _store(tmp_path)
    # Project A: 2 events
    write_pack_event(
        store=s,
        project_root="/a",
        os_user="alice",
        query="q1",
        mode="navigate",
        paths_touched=[],
    )
    time.sleep(0.01)
    # Project B: 1 event but newer
    write_pack_event(
        store=s,
        project_root="/b",
        os_user="alice",
        query="q2",
        mode="navigate",
        paths_touched=[],
    )
    # Another event in project A
    write_pack_event(
        store=s,
        project_root="/a",
        os_user="alice",
        query="q3",
        mode="navigate",
        paths_touched=[],
    )
    digest = load_cross_project(store=s, os_user="alice", since_ts=0, limit=10)
    assert [d.project_root for d in digest] == ["/a", "/b"]
    assert digest[0].count == 2
    assert digest[1].count == 1
