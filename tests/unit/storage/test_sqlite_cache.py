import sqlite3
from pathlib import Path

import pytest
from libs.core.entities import File, Relation, RelationType, Symbol, SymbolType
from libs.storage.sqlite_cache import SqliteCache


@pytest.fixture
def cache(tmp_path: Path) -> SqliteCache:
    c = SqliteCache(tmp_path / "cache.db")
    c.migrate()
    return c


def test_put_and_get_file(cache: SqliteCache) -> None:
    f = File(
        path="app/main.py",
        content_hash="a" * 64,
        size_bytes=100,
        language="python",
        role="source",
    )
    cache.put_file(f)
    got = cache.get_file("app/main.py")
    assert got == f


def test_put_file_is_idempotent(cache: SqliteCache) -> None:
    f = File(
        path="a.py",
        content_hash="h1",
        size_bytes=1,
        language="python",
        role="source",
    )
    cache.put_file(f)
    cache.put_file(f)
    assert cache.file_count() == 1


def test_update_file_replaces_row(cache: SqliteCache) -> None:
    f1 = File(
        path="a.py",
        content_hash="h1",
        size_bytes=1,
        language="python",
        role="source",
    )
    f2 = File(
        path="a.py",
        content_hash="h2",
        size_bytes=2,
        language="python",
        role="source",
    )
    cache.put_file(f1)
    cache.put_file(f2)
    assert cache.get_file("a.py") == f2
    assert cache.file_count() == 1


def test_delete_file(cache: SqliteCache) -> None:
    f = File(
        path="a.py",
        content_hash="h",
        size_bytes=1,
        language="python",
        role="source",
    )
    cache.put_file(f)
    cache.delete_file("a.py")
    assert cache.get_file("a.py") is None


def test_put_and_list_symbols(cache: SqliteCache) -> None:
    # A symbol needs a parent file row because of FK
    f = File(
        path="app/models/user.py",
        content_hash="h",
        size_bytes=1,
        language="python",
        role="source",
    )
    cache.put_file(f)

    s = Symbol(
        name="User",
        fq_name="app.models.user.User",
        symbol_type=SymbolType.CLASS,
        file_path="app/models/user.py",
        start_line=1,
        end_line=20,
    )
    cache.replace_symbols(file_path="app/models/user.py", symbols=(s,))
    got = list(cache.iter_symbols())
    assert got == [s]


def test_replace_symbols_removes_old(cache: SqliteCache) -> None:
    f = File(
        path="x.py",
        content_hash="h",
        size_bytes=1,
        language="python",
        role="source",
    )
    cache.put_file(f)

    s1 = Symbol(
        name="Old",
        fq_name="x.Old",
        symbol_type=SymbolType.CLASS,
        file_path="x.py",
        start_line=1,
        end_line=2,
    )
    s2 = Symbol(
        name="New",
        fq_name="x.New",
        symbol_type=SymbolType.CLASS,
        file_path="x.py",
        start_line=1,
        end_line=2,
    )
    cache.replace_symbols(file_path="x.py", symbols=(s1,))
    cache.replace_symbols(file_path="x.py", symbols=(s2,))
    names = {s.name for s in cache.iter_symbols()}
    assert names == {"New"}


def test_replace_relations(cache: SqliteCache) -> None:
    f = File(
        path="a.py",
        content_hash="h",
        size_bytes=1,
        language="python",
        role="source",
    )
    cache.put_file(f)

    r = Relation(
        src_type="file",
        src_ref="a.py",
        dst_type="module",
        dst_ref="datetime",
        relation_type=RelationType.IMPORTS,
    )
    cache.replace_relations(file_path="a.py", relations=(r,))
    got = list(cache.iter_relations())
    assert len(got) == 1
    assert got[0].dst_ref == "datetime"


def test_sqlite_cache_is_context_manager(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    with SqliteCache(db) as cache:
        cache.migrate()
        cache.put_file(
            File(
                path="a.py",
                content_hash="h",
                size_bytes=1,
                language="python",
                role="source",
            )
        )
    # After context exit, cache is closed — reconnecting should work
    cache2 = SqliteCache(db)
    cache2.migrate()
    assert cache2.get_file("a.py") is not None
    cache2.close()


def test_migrate_forward_compatible_with_future_version(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    with SqliteCache(db) as cache:
        cache.migrate()
        # Simulate a future-version DB by manually bumping user_version
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()

    # Reopening with older binary must NOT crash — forward compatible
    with SqliteCache(db) as cache2:
        cache2.migrate()  # should silently proceed


def test_delete_file_cascades_relations(cache: SqliteCache) -> None:
    f = File(
        path="a.py",
        content_hash="h",
        size_bytes=1,
        language="python",
        role="source",
    )
    cache.put_file(f)
    r = Relation(
        src_type="file",
        src_ref="a.py",
        dst_type="module",
        dst_ref="datetime",
        relation_type=RelationType.IMPORTS,
    )
    cache.replace_relations(file_path="a.py", relations=(r,))
    assert len(list(cache.iter_relations())) == 1

    cache.delete_file("a.py")

    # After delete, relations from that file must be gone
    assert list(cache.iter_relations()) == []


def test_put_file_persists_has_secrets_flag(cache: SqliteCache) -> None:
    f = File(
        path="config/production.yaml",
        content_hash="h",
        size_bytes=100,
        language="yaml",
        role="config",
        has_secrets=True,
    )
    cache.put_file(f)
    got = cache.get_file("config/production.yaml")
    assert got is not None
    assert got.has_secrets is True


def test_retrieval_traces_table_exists(cache: SqliteCache) -> None:
    # The retrieval_traces table is created by migrate(); insert and read a row
    import json

    conn = sqlite3.connect(cache.db_path)
    conn.execute(
        "INSERT INTO retrieval_traces (trace_id, project, query, mode, timestamp, coverage, trace_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("t1", "demo", "login endpoint", "navigate", 1000.0, "high", json.dumps({"stages": []})),
    )
    conn.commit()
    row = conn.execute(
        "SELECT trace_id, coverage FROM retrieval_traces WHERE trace_id = ?",
        ("t1",),
    ).fetchone()
    conn.close()
    assert row == ("t1", "high")


def test_embedding_model_migrations_table_exists(cache: SqliteCache) -> None:
    """spec #1 T004: per-project re-embedding run ledger.

    Verifies the v5 schema bump lands the table + indexes + CHECK constraint.
    """
    conn = sqlite3.connect(cache.db_path)
    conn.execute(
        """
        INSERT INTO embedding_model_migrations
            (from_model, to_model, started_at, status)
        VALUES (?, ?, ?, ?)
        """,
        ("text-embedding-3-small", "bge-m3-v1", 1_700_000_000.0, "running"),
    )
    conn.commit()
    row = conn.execute(
        "SELECT from_model, to_model, status, points_total, points_migrated "
        "FROM embedding_model_migrations "
        "WHERE from_model = ? AND to_model = ?",
        ("text-embedding-3-small", "bge-m3-v1"),
    ).fetchone()
    assert row == ("text-embedding-3-small", "bge-m3-v1", "running", 0, 0)

    # CHECK constraint rejects bogus statuses
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO embedding_model_migrations
                (from_model, to_model, started_at, status)
            VALUES (?, ?, ?, ?)
            """,
            ("a", "b", 1.0, "bogus"),
        )
        conn.commit()
    conn.close()


def test_v4_cache_migrates_to_v5_and_gets_embedding_table(tmp_path: Path) -> None:
    """Simulate an on-disk v4 cache and verify migrate() lands v5 table.

    Regression guard: v4 -> v5 chain must add embedding_model_migrations
    without dropping existing rows.
    """
    db_path = tmp_path / "cache.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE files (
            path          TEXT PRIMARY KEY,
            content_hash  TEXT NOT NULL,
            size_bytes    INTEGER NOT NULL,
            language      TEXT NOT NULL,
            role          TEXT NOT NULL,
            is_generated  INTEGER NOT NULL DEFAULT 0,
            is_binary     INTEGER NOT NULL DEFAULT 0,
            has_secrets   INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE git_stats (
            file_path       TEXT PRIMARY KEY,
            commit_count    INTEGER NOT NULL DEFAULT 0,
            churn_30d       INTEGER NOT NULL DEFAULT 0,
            last_modified_ts REAL NOT NULL DEFAULT 0,
            age_days        INTEGER NOT NULL DEFAULT 0,
            authors_json    TEXT NOT NULL DEFAULT '[]',
            primary_author  TEXT NOT NULL DEFAULT '',
            last_author     TEXT NOT NULL DEFAULT '',
            computed_at_ts  REAL NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("a.py", "h", 1, "python", "source", 0, 0, 0),
    )
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    cache = SqliteCache(db_path)
    cache.migrate()

    conn = sqlite3.connect(db_path)
    # Existing row survives the migration.
    assert conn.execute("SELECT path FROM files").fetchone() == ("a.py",)
    # New table is present.
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "embedding_model_migrations" in tables
    assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 5
    conn.close()
