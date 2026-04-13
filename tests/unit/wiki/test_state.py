"""Tests for libs/wiki/state.py — dirty tracking, hash computation."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from libs.wiki.state import (
    compute_module_hash,
    ensure_wiki_table,
    get_all_modules,
    get_dirty_modules,
    mark_current,
    mark_dirty,
    update_dirty_state,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    """In-memory SQLite connection with wiki_state table."""
    c = sqlite3.connect(":memory:")
    ensure_wiki_table(c)
    c.commit()
    return c


class TestEnsureWikiTable:
    def test_creates_table(self, conn: sqlite3.Connection) -> None:
        # Table should exist after ensure_wiki_table
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_state'"
        ).fetchone()
        assert row is not None

    def test_idempotent(self, conn: sqlite3.Connection) -> None:
        # Calling twice should not raise
        ensure_wiki_table(conn)
        ensure_wiki_table(conn)


class TestComputeModuleHash:
    def test_deterministic(self) -> None:
        hashes = ["abc", "def", "ghi"]
        h1 = compute_module_hash(hashes)
        h2 = compute_module_hash(hashes)
        assert h1 == h2

    def test_order_independent(self) -> None:
        h1 = compute_module_hash(["abc", "def"])
        h2 = compute_module_hash(["def", "abc"])
        assert h1 == h2

    def test_different_inputs_different_hash(self) -> None:
        h1 = compute_module_hash(["abc"])
        h2 = compute_module_hash(["xyz"])
        assert h1 != h2

    def test_empty_list(self) -> None:
        h = compute_module_hash([])
        assert isinstance(h, str)
        assert len(h) == 64  # SHA256 hex length


class TestMarkDirty:
    def test_inserts_dirty_module(self, conn: sqlite3.Connection) -> None:
        mark_dirty(conn, "libs/core", "hash123")
        conn.commit()

        modules = get_dirty_modules(conn)
        assert len(modules) == 1
        assert modules[0]["module_path"] == "libs/core"
        assert modules[0]["status"] == "dirty"
        assert modules[0]["source_hash"] == "hash123"

    def test_replaces_on_duplicate(self, conn: sqlite3.Connection) -> None:
        mark_dirty(conn, "libs/core", "hash1")
        conn.commit()
        mark_dirty(conn, "libs/core", "hash2")
        conn.commit()

        modules = get_all_modules(conn)
        assert len(modules) == 1
        assert modules[0]["source_hash"] == "hash2"


class TestMarkCurrent:
    def test_marks_current(self, conn: sqlite3.Connection) -> None:
        mark_dirty(conn, "libs/core", "hash1")
        conn.commit()

        mark_current(conn, "libs/core", "modules/libs-core.md", "hash1")
        conn.commit()

        dirty = get_dirty_modules(conn)
        assert len(dirty) == 0

        all_mods = get_all_modules(conn)
        assert len(all_mods) == 1
        assert all_mods[0]["status"] == "current"
        assert all_mods[0]["wiki_file"] == "modules/libs-core.md"
        assert all_mods[0]["last_generated_ts"] > 0


class TestGetModules:
    def test_get_dirty_only(self, conn: sqlite3.Connection) -> None:
        mark_dirty(conn, "libs/core", "h1")
        mark_dirty(conn, "libs/wiki", "h2")
        conn.commit()

        mark_current(conn, "libs/core", "modules/libs-core.md", "h1")
        conn.commit()

        dirty = get_dirty_modules(conn)
        assert len(dirty) == 1
        assert dirty[0]["module_path"] == "libs/wiki"

    def test_get_all(self, conn: sqlite3.Connection) -> None:
        mark_dirty(conn, "libs/core", "h1")
        mark_dirty(conn, "libs/wiki", "h2")
        conn.commit()

        all_mods = get_all_modules(conn)
        assert len(all_mods) == 2


class TestUpdateDirtyState:
    def test_marks_new_modules_dirty(self, conn: sqlite3.Connection) -> None:
        files = [
            SimpleNamespace(path="libs/core/entities.py", content_hash="aaa"),
            SimpleNamespace(path="libs/core/config.py", content_hash="bbb"),
            SimpleNamespace(path="apps/cli/main.py", content_hash="ccc"),
        ]
        count = update_dirty_state(conn, files)
        conn.commit()

        assert count == 2  # libs/core and apps/cli
        dirty = get_dirty_modules(conn)
        paths = {m["module_path"] for m in dirty}
        assert paths == {"libs/core", "apps/cli"}

    def test_unchanged_module_not_dirty(self, conn: sqlite3.Connection) -> None:
        files = [
            SimpleNamespace(path="libs/core/a.py", content_hash="aaa"),
        ]
        update_dirty_state(conn, files)
        conn.commit()

        # Mark current
        mods = get_dirty_modules(conn)
        for m in mods:
            mark_current(conn, m["module_path"], m["wiki_file"], m["source_hash"])
        conn.commit()

        # Same files again — should not be marked dirty
        count = update_dirty_state(conn, files)
        conn.commit()

        assert count == 0
        assert len(get_dirty_modules(conn)) == 0

    def test_changed_hash_marks_dirty(self, conn: sqlite3.Connection) -> None:
        files = [SimpleNamespace(path="libs/core/a.py", content_hash="aaa")]
        update_dirty_state(conn, files)
        conn.commit()

        for m in get_dirty_modules(conn):
            mark_current(conn, m["module_path"], m["wiki_file"], m["source_hash"])
        conn.commit()

        # Change the hash
        files = [SimpleNamespace(path="libs/core/a.py", content_hash="bbb")]
        count = update_dirty_state(conn, files)
        conn.commit()

        assert count == 1
        assert len(get_dirty_modules(conn)) == 1

    def test_single_segment_path(self, conn: sqlite3.Connection) -> None:
        files = [SimpleNamespace(path="README.md", content_hash="xxx")]
        count = update_dirty_state(conn, files)
        conn.commit()
        assert count == 1
        mods = get_dirty_modules(conn)
        assert mods[0]["module_path"] == "README.md"
