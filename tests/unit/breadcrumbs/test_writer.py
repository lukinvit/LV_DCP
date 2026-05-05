"""Tests for breadcrumb writers."""

from __future__ import annotations

import json
from pathlib import Path

from libs.breadcrumbs.models import BreadcrumbSource
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import (
    write_hook_event,
    write_pack_event,
    write_status_event,
)


def _store(tmp_path: Path) -> BreadcrumbStore:
    s = BreadcrumbStore(db_path=tmp_path / "bc.db")
    s.migrate()
    return s


def test_write_pack_event_persists_row(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/repo/foo",
        os_user="alice",
        query="how does X work",
        mode="navigate",
        paths_touched=[
            "src/x.py",
            "src/y.py",
            "src/z.py",
            "src/a.py",
            "src/b.py",
            "src/c.py",
        ],
        cc_session_id="sess1",
        cc_account_email="alice@example.com",
    )
    rows = list(
        s.connect().execute(
            "SELECT source, query, paths_touched, cc_session_id FROM breadcrumbs"
        )
    )
    assert len(rows) == 1
    assert rows[0][0] == "pack"
    assert rows[0][1] == "how does X work"
    assert json.loads(rows[0][2]) == [
        "src/x.py",
        "src/y.py",
        "src/z.py",
        "src/a.py",
        "src/b.py",
    ]  # top-5
    assert rows[0][3] == "sess1"


def test_write_pack_event_redacts_secrets(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_pack_event(
        store=s,
        project_root="/repo/foo",
        os_user="alice",
        query="why does sk-1234567890ABCDEFGHIJ fail",
        mode="navigate",
        paths_touched=[],
    )
    row = s.connect().execute("SELECT query FROM breadcrumbs").fetchone()
    assert row is not None
    q = row[0]
    assert "[REDACTED:openai]" in q
    assert "sk-1234567890ABCDEFGHIJ" not in q


def test_write_hook_event_with_todo_snapshot(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_hook_event(
        store=s,
        source=BreadcrumbSource.HOOK_STOP,
        project_root="/repo/foo",
        os_user="alice",
        cc_session_id="sess1",
        todo_snapshot=[{"content": "task A", "status": "completed"}],
    )
    row = s.connect().execute("SELECT todo_snapshot FROM breadcrumbs").fetchone()
    assert row is not None
    assert json.loads(row[0]) == [{"content": "task A", "status": "completed"}]


def test_write_status_event(tmp_path: Path) -> None:
    s = _store(tmp_path)
    write_status_event(
        store=s,
        project_root="/repo/foo",
        os_user="alice",
    )
    row = s.connect().execute("SELECT source FROM breadcrumbs").fetchone()
    assert row is not None
    assert row[0] == "status"


def test_writer_swallows_exception(tmp_path: Path) -> None:
    """Writer must never propagate exceptions — observability only."""
    bad_store = BreadcrumbStore(db_path=tmp_path / "nonexistent" / "subdir" / "bc.db")
    # No migrate() call → table missing
    write_pack_event(
        store=bad_store,
        project_root="/x",
        os_user="alice",
        query="q",
        mode="navigate",
        paths_touched=[],
    )
    # Should not raise
