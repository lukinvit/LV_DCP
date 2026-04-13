"""Tests for apps/agent/wiki_worker.py — background wiki update task."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from apps.agent.wiki_worker import run_wiki_update
from libs.core.projects_config import WikiConfig
from libs.wiki.state import ensure_wiki_table, mark_dirty


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Minimal project with cache.db, wiki dir, and one dirty module."""
    ctx = tmp_path / ".context"
    ctx.mkdir()
    wiki = ctx / "wiki"
    wiki.mkdir()
    (wiki / "modules").mkdir()

    db = ctx / "cache.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            language TEXT NOT NULL DEFAULT 'python',
            role TEXT NOT NULL DEFAULT 'source',
            is_generated INTEGER NOT NULL DEFAULT 0,
            is_binary INTEGER NOT NULL DEFAULT 0,
            has_secrets INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fq_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            symbol_type TEXT NOT NULL DEFAULT 'function'
        );
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_ref TEXT NOT NULL,
            dst_ref TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'imports'
        );
    """)
    ensure_wiki_table(conn)
    conn.execute(
        "INSERT INTO files (path, content_hash, size_bytes) VALUES (?, ?, ?)",
        ("libs/core/entities.py", "abc123", 500),
    )
    mark_dirty(conn, "libs/core", "hash_old")
    conn.commit()
    conn.close()
    return tmp_path


def test_calls_generate_for_dirty_modules(project: Path) -> None:
    config = WikiConfig(article_max_tokens=500)
    article_text = "# libs/core\n\n## Purpose\nCore module.\n"
    with (
        patch("apps.agent.wiki_worker.generate_wiki_article", return_value=article_text) as mock_gen,
        patch("apps.agent.wiki_worker.write_index"),
    ):
        run_wiki_update(project, config)
    mock_gen.assert_called_once()
    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs["module_path"] == "libs/core"
    assert call_kwargs["project_name"] == project.name
    assert call_kwargs["max_tokens"] == 500


def test_writes_article_file(project: Path) -> None:
    config = WikiConfig()
    article_text = "# libs/core\n\n## Purpose\nCore module.\n"
    with (
        patch("apps.agent.wiki_worker.generate_wiki_article", return_value=article_text),
        patch("apps.agent.wiki_worker.write_index"),
    ):
        run_wiki_update(project, config)
    article_path = project / ".context" / "wiki" / "modules" / "libs-core.md"
    assert article_path.exists()
    assert article_path.read_text() == article_text


def test_continues_on_module_error(project: Path) -> None:
    """Error on one module must not abort others."""
    db = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO files (path, content_hash, size_bytes) VALUES (?, ?, ?)",
        ("libs/scanning/scanner.py", "def456", 800),
    )
    mark_dirty(conn, "libs/scanning", "hash_scan")
    conn.commit()
    conn.close()

    results: list[str] = []

    def fake_generate(**kwargs: object) -> str:
        mod = str(kwargs["module_path"])
        if mod == "libs/core":
            raise RuntimeError("Claude CLI timeout")
        results.append(mod)
        return f"# {mod}\n\n## Purpose\nDoes things.\n"

    config = WikiConfig()
    with (
        patch("apps.agent.wiki_worker.generate_wiki_article", side_effect=fake_generate),
        patch("apps.agent.wiki_worker.write_index"),
    ):
        run_wiki_update(project, config)

    assert "libs/scanning" in results


def test_no_op_when_no_cache_db(tmp_path: Path) -> None:
    config = WikiConfig()
    with patch("apps.agent.wiki_worker.generate_wiki_article") as mock_gen:
        run_wiki_update(tmp_path, config)
    mock_gen.assert_not_called()


def test_no_op_when_no_dirty_modules(project: Path) -> None:
    db = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE wiki_state SET status = 'current' WHERE module_path = 'libs/core'")
    conn.commit()
    conn.close()

    config = WikiConfig()
    with (
        patch("apps.agent.wiki_worker.generate_wiki_article") as mock_gen,
        patch("apps.agent.wiki_worker.write_index"),
    ):
        run_wiki_update(project, config)
    mock_gen.assert_not_called()


def test_respects_max_modules_per_run(project: Path) -> None:
    db = project / ".context" / "cache.db"
    conn = sqlite3.connect(str(db))
    for i in range(5):
        conn.execute(
            "INSERT OR IGNORE INTO files (path, content_hash, size_bytes) VALUES (?, ?, ?)",
            (f"libs/mod{i}/a.py", f"hash{i}", 100),
        )
        mark_dirty(conn, f"libs/mod{i}", f"hash{i}")
    conn.commit()
    conn.close()

    config = WikiConfig(max_modules_per_run=2)
    generated: list[str] = []

    def fake_gen(**kwargs: object) -> str:
        generated.append(str(kwargs["module_path"]))
        return "# mod\n\n## Purpose\nDoes things.\n"

    with (
        patch("apps.agent.wiki_worker.generate_wiki_article", side_effect=fake_gen),
        patch("apps.agent.wiki_worker.write_index"),
    ):
        run_wiki_update(project, config)

    assert len(generated) <= 2
