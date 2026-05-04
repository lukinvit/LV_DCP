import sqlite3
from pathlib import Path

from libs.breadcrumbs.store import BreadcrumbStore


def test_migrate_creates_table_and_indexes(tmp_path: Path) -> None:
    db = tmp_path / "breadcrumbs.db"
    store = BreadcrumbStore(db_path=db)
    store.migrate()
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    assert "breadcrumbs" in tables
    assert "ix_breadcrumbs_root_ts" in indexes
    assert "ix_breadcrumbs_user_root_ts" in indexes
    assert "ix_breadcrumbs_session" in indexes


def test_migrate_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "breadcrumbs.db"
    store = BreadcrumbStore(db_path=db)
    store.migrate()
    store.migrate()  # second call must not raise
    store.close()
