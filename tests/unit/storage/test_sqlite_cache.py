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


def test_migrate_rejects_future_version(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    with SqliteCache(db) as cache:
        cache.migrate()
        # Simulate a future-version DB by manually bumping user_version
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()

    # Reopening with the same binary must refuse to migrate
    with pytest.raises(RuntimeError, match="schema version 99"), SqliteCache(db) as cache2:
        cache2.migrate()


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
