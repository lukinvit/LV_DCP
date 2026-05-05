from pathlib import Path

import pytest
from libs.breadcrumbs.store import BreadcrumbStore


def test_status_writes_breadcrumb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.mcp.tools.DEFAULT_STORE_PATH", db)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    from apps.mcp.tools import _record_status_breadcrumb

    _record_status_breadcrumb(project_root=str(tmp_path))
    s = BreadcrumbStore(db_path=db)
    s.migrate()
    row = s.connect().execute("SELECT source FROM breadcrumbs").fetchone()
    s.close()
    assert row is not None
    assert row[0] == "status"
