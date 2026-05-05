"""Tests for the lvdcp_resume MCP tool."""

from __future__ import annotations

import getpass
from pathlib import Path

import pytest
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event


def test_lvdcp_resume_project_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.mcp.tools.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db)
    s.migrate()
    write_pack_event(
        store=s,
        project_root=str(tmp_path),
        os_user=getpass.getuser(),
        query="how does X work",
        mode="navigate",
        paths_touched=["src/x.py"],
    )
    s.close()

    from apps.mcp.tools import lvdcp_resume

    out = lvdcp_resume(path=str(tmp_path), scope="project", limit=10, format="markdown")
    assert out.scope == "project"
    assert "Resume:" in out.markdown
    assert "how does X work" in out.markdown


def test_lvdcp_resume_cross_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.mcp.tools.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db)
    s.migrate()
    write_pack_event(
        store=s,
        project_root="/a",
        os_user=getpass.getuser(),
        query="qa",
        mode="navigate",
        paths_touched=[],
    )
    write_pack_event(
        store=s,
        project_root="/b",
        os_user=getpass.getuser(),
        query="qb",
        mode="edit",
        paths_touched=[],
    )
    s.close()

    from apps.mcp.tools import lvdcp_resume

    out = lvdcp_resume(path=None, scope="cross_project", limit=10, format="markdown")
    assert out.scope == "cross_project"
    assert "/a" in out.markdown and "/b" in out.markdown
