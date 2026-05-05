"""Tests for markdown renderer — full + inject modes."""

from __future__ import annotations

import getpass
import time
from pathlib import Path

from libs.breadcrumbs.renderer import render_cross_project, render_inject, render_project_pack
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.views import build_cross_project_resume_pack, build_project_resume_pack
from libs.breadcrumbs.writer import write_pack_event


def test_render_project_pack_includes_branch_and_query(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    write_pack_event(
        store=s,
        project_root=str(tmp_path),
        os_user=getpass.getuser(),
        query="how does X work",
        mode="navigate",
        paths_touched=["src/x.py"],
    )
    pack = build_project_resume_pack(
        store=s,
        project_root=tmp_path,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    md = render_project_pack(pack)
    assert "## Resume" in md
    assert "how does X work" in md
    assert "src/x.py" in md


def test_render_inject_under_2kb(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    for i in range(50):
        write_pack_event(
            store=s,
            project_root=str(tmp_path),
            os_user=getpass.getuser(),
            query=f"query {i}",
            mode="navigate",
            paths_touched=[f"src/f{i}.py"],
        )
    pack = build_project_resume_pack(
        store=s,
        project_root=tmp_path,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    md = render_inject(pack)
    assert len(md.encode("utf-8")) <= 2048


def test_render_empty_pack_returns_empty_string(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    pack = build_project_resume_pack(
        store=s,
        project_root=tmp_path,
        os_user=getpass.getuser(),
        cc_account_email=None,
        since_ts=0.0,
        limit=100,
    )
    assert render_inject(pack) == ""


def test_render_cross_project(tmp_path: Path) -> None:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    write_pack_event(
        store=s,
        project_root="/a",
        os_user=getpass.getuser(),
        query="qa",
        mode="navigate",
        paths_touched=[],
    )
    time.sleep(0.01)
    write_pack_event(
        store=s,
        project_root="/b",
        os_user=getpass.getuser(),
        query="qb",
        mode="edit",
        paths_touched=[],
    )
    pack = build_cross_project_resume_pack(
        store=s, os_user=getpass.getuser(), since_ts=0.0, limit=10
    )
    md = render_cross_project(pack)
    assert "/a" in md and "/b" in md
