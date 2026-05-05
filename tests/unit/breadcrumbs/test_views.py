"""Tests for ResumePack assemblers and FocusGuess synthesis."""

from __future__ import annotations

import time
from pathlib import Path

from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.views import (
    ProjectResumePack,
    build_cross_project_resume_pack,
    build_project_resume_pack,
)
from libs.breadcrumbs.writer import write_pack_event


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_project_resume_pack_with_breadcrumbs(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root=str(tmp_path),
        os_user="alice",
        query="how does X work",
        mode="navigate",
        paths_touched=["src/x.py", "src/x.py", "src/y.py"],
    )
    pack = build_project_resume_pack(
        store=s,
        project_root=tmp_path,
        os_user="alice",
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert isinstance(pack, ProjectResumePack)
    assert pack.breadcrumbs_empty is False
    assert pack.inferred_focus.last_query == "how does X work"
    assert pack.inferred_focus.last_mode == "navigate"
    assert "src/x.py" in [str(p) for p in pack.inferred_focus.hot_files]


def test_project_resume_pack_empty(tmp_path: Path) -> None:
    s = _store(tmp_path)
    pack = build_project_resume_pack(
        store=s,
        project_root=tmp_path,
        os_user="alice",
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert pack.breadcrumbs_empty is True
    assert pack.inferred_focus.last_query is None


def test_cross_project_resume_orders_by_recency(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/a",
        os_user="alice",
        query="q1",
        mode="navigate",
        paths_touched=[],
    )
    time.sleep(0.01)
    write_pack_event(
        store=s,
        project_root="/b",
        os_user="alice",
        query="q2",
        mode="edit",
        paths_touched=[],
    )
    pack = build_cross_project_resume_pack(
        store=s, os_user="alice", since_ts=0.0, limit=10
    )
    assert pack.scope == "cross_project"
    assert pack.digest is not None
    assert [d.project_root for d in pack.digest] == ["/b", "/a"]
