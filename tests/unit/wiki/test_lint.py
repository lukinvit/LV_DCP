"""Tests for libs/wiki/lint.py — all 5 lint checks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from libs.wiki.lint import lint_wiki
from libs.wiki.state import ensure_wiki_table, mark_current, mark_dirty


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project structure with cache.db and wiki dir."""
    context_dir = tmp_path / ".context"
    context_dir.mkdir()
    wiki_dir = context_dir / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "modules").mkdir()

    # Create cache.db with files table and wiki_state
    db_path = context_dir / "cache.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            path          TEXT PRIMARY KEY,
            content_hash  TEXT NOT NULL,
            size_bytes    INTEGER NOT NULL,
            language      TEXT NOT NULL,
            role          TEXT NOT NULL,
            is_generated  INTEGER NOT NULL DEFAULT 0,
            is_binary     INTEGER NOT NULL DEFAULT 0,
            has_secrets   INTEGER NOT NULL DEFAULT 0
        );
    """)
    ensure_wiki_table(conn)
    conn.commit()
    conn.close()
    return tmp_path


def _add_files(project: Path, file_paths: list[str]) -> None:
    """Insert file records into cache.db."""
    db_path = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db_path))
    for fp in file_paths:
        conn.execute(
            "INSERT OR REPLACE INTO files (path, content_hash, size_bytes, language, role) "
            "VALUES (?, 'hash123', 100, 'python', 'source')",
            (fp,),
        )
    conn.commit()
    conn.close()


def _create_article(
    project: Path, stem: str, content: str = "# Module\n\n## Purpose\nDoes things.\n"
) -> None:
    """Write a wiki article file."""
    modules_dir = project / ".context" / "wiki" / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / f"{stem}.md").write_text(content, encoding="utf-8")


def _write_index(project: Path, entries: list[str]) -> None:
    """Write INDEX.md with given module entry lines."""
    wiki_dir = project / ".context" / "wiki"
    lines = ["# Wiki Index — Test", "", "## Modules"]
    lines.extend(entries)
    lines.append("")
    (wiki_dir / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


class TestOrphanedArticles:
    """Check 1: wiki article exists but module has no files in cache.db."""

    def test_orphaned_article_detected(self, project: Path) -> None:
        # Article exists but no files for this module
        _create_article(project, "libs-gone")
        _write_index(project, ["- [libs-gone](modules/libs-gone.md) — Gone module."])

        issues = lint_wiki(project)
        orphaned = [i for i in issues if "Orphaned" in i.message]
        assert len(orphaned) == 1
        assert orphaned[0].module_path == "libs-gone"
        assert orphaned[0].severity == "warning"

    def test_no_orphan_when_files_exist(self, project: Path) -> None:
        _add_files(project, ["libs/core/entities.py"])
        _create_article(project, "libs-core")
        _write_index(project, ["- [libs-core](modules/libs-core.md) — Core module."])

        issues = lint_wiki(project)
        orphaned = [i for i in issues if "Orphaned" in i.message]
        assert len(orphaned) == 0


class TestMissingArticles:
    """Check 2: module has files but no wiki article."""

    def test_missing_article_detected(self, project: Path) -> None:
        _add_files(project, ["libs/core/entities.py", "libs/core/config.py"])
        # No article created for libs-core
        _write_index(project, [])

        issues = lint_wiki(project)
        missing = [i for i in issues if "Missing" in i.message]
        assert len(missing) == 1
        assert missing[0].module_path == "libs/core"
        assert missing[0].severity == "warning"

    def test_no_missing_when_article_exists(self, project: Path) -> None:
        _add_files(project, ["libs/core/entities.py"])
        _create_article(project, "libs-core")
        _write_index(project, ["- [libs-core](modules/libs-core.md) — Core."])

        issues = lint_wiki(project)
        missing = [i for i in issues if "Missing" in i.message]
        assert len(missing) == 0


class TestStaleArticles:
    """Check 3: wiki_state.status = 'dirty'."""

    def test_stale_detected(self, project: Path) -> None:
        _add_files(project, ["libs/wiki/gen.py"])
        _create_article(project, "libs-wiki")
        _write_index(project, ["- [libs-wiki](modules/libs-wiki.md) — Wiki."])

        # Mark dirty in wiki_state
        db_path = project / ".context" / "cache.db"
        conn = sqlite3.connect(str(db_path))
        ensure_wiki_table(conn)
        mark_dirty(conn, "libs/wiki", "hash_new")
        conn.commit()
        conn.close()

        issues = lint_wiki(project)
        stale = [i for i in issues if "Stale" in i.message]
        assert len(stale) == 1
        assert stale[0].module_path == "libs/wiki"

    def test_no_stale_when_current(self, project: Path) -> None:
        _add_files(project, ["libs/wiki/gen.py"])
        _create_article(project, "libs-wiki")
        _write_index(project, ["- [libs-wiki](modules/libs-wiki.md) — Wiki."])

        db_path = project / ".context" / "cache.db"
        conn = sqlite3.connect(str(db_path))
        ensure_wiki_table(conn)
        mark_dirty(conn, "libs/wiki", "hash1")
        mark_current(conn, "libs/wiki", "modules/libs-wiki.md", "hash1")
        conn.commit()
        conn.close()

        issues = lint_wiki(project)
        stale = [i for i in issues if "Stale" in i.message]
        assert len(stale) == 0


class TestEmptyArticles:
    """Check 4: article file exists but is < 50 bytes."""

    def test_empty_detected(self, project: Path) -> None:
        _add_files(project, ["libs/tiny/a.py"])
        _create_article(project, "libs-tiny", content="# Hi\n")  # 6 bytes
        _write_index(project, ["- [libs-tiny](modules/libs-tiny.md)"])

        issues = lint_wiki(project)
        empty = [i for i in issues if "Empty" in i.message]
        assert len(empty) == 1
        assert empty[0].severity == "error"
        assert empty[0].module_path == "libs-tiny"

    def test_no_empty_when_sufficient(self, project: Path) -> None:
        _add_files(project, ["libs/big/a.py"])
        _create_article(project, "libs-big", content="x" * 100)
        _write_index(project, ["- [libs-big](modules/libs-big.md)"])

        issues = lint_wiki(project)
        empty = [i for i in issues if "Empty" in i.message]
        assert len(empty) == 0


class TestIndexMismatch:
    """Check 5: article in modules/ but not in INDEX.md, or vice versa."""

    def test_article_not_in_index(self, project: Path) -> None:
        _add_files(project, ["libs/core/a.py"])
        _create_article(project, "libs-core")
        # INDEX.md has no entries
        _write_index(project, [])

        issues = lint_wiki(project)
        mismatch = [
            i for i in issues if "INDEX mismatch" in i.message and "not listed" in i.message
        ]
        assert len(mismatch) == 1
        assert mismatch[0].module_path == "libs-core"

    def test_index_entry_no_article(self, project: Path) -> None:
        # INDEX references a module that has no article file
        _write_index(project, ["- [libs-phantom](modules/libs-phantom.md) — Ghost."])

        issues = lint_wiki(project)
        mismatch = [
            i for i in issues if "INDEX mismatch" in i.message and "no article file" in i.message
        ]
        assert len(mismatch) == 1
        assert mismatch[0].module_path == "libs-phantom"

    def test_no_mismatch_when_aligned(self, project: Path) -> None:
        _add_files(project, ["libs/core/a.py"])
        _create_article(project, "libs-core")
        _write_index(project, ["- [libs-core](modules/libs-core.md) — Core."])

        issues = lint_wiki(project)
        mismatch = [i for i in issues if "INDEX mismatch" in i.message]
        assert len(mismatch) == 0


class TestNoCacheDb:
    """Edge case: no cache.db at all."""

    def test_returns_error(self, tmp_path: Path) -> None:
        issues = lint_wiki(tmp_path)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert "cache.db" in issues[0].message
