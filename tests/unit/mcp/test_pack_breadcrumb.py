"""Tests for the fire-and-forget breadcrumb side-effect in lvdcp_pack."""

from pathlib import Path

import pytest
from libs.breadcrumbs.store import BreadcrumbStore


def test_pack_writes_breadcrumb_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.mcp.tools.DEFAULT_STORE_PATH", db)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # Simulate a successful pack call by invoking the helper directly
    from apps.mcp.tools import _record_pack_breadcrumb

    _record_pack_breadcrumb(
        project_root=str(tmp_path),
        query="how does X work",
        mode="navigate",
        retrieved_files=["src/x.py", "src/y.py", "src/z.py", "src/a.py", "src/b.py", "src/c.py"],
    )
    s = BreadcrumbStore(db_path=db)
    s.migrate()
    rows = list(s.connect().execute("SELECT source, query FROM breadcrumbs"))
    s.close()
    assert len(rows) == 1
    assert rows[0] == ("pack", "how does X work")


def test_pack_breadcrumb_helper_swallows_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "libs.breadcrumbs.store.DEFAULT_STORE_PATH",
        tmp_path / "no" / "such" / "dir" / "bc.db",
    )
    monkeypatch.setattr(
        "apps.mcp.tools.DEFAULT_STORE_PATH",
        tmp_path / "no" / "such" / "dir" / "bc.db",
    )
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    from apps.mcp.tools import _record_pack_breadcrumb

    # must not raise
    _record_pack_breadcrumb(project_root="/x", query="q", mode="navigate", retrieved_files=[])
