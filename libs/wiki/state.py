"""Wiki state tracking in SQLite cache.

Tracks which modules are dirty (source changed since last wiki generation)
and which are current.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS wiki_state (
    module_path TEXT PRIMARY KEY,
    wiki_file TEXT NOT NULL,
    last_generated_ts REAL NOT NULL DEFAULT 0,
    source_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'dirty'
);
"""


def ensure_wiki_table(conn: sqlite3.Connection) -> None:
    """Create wiki_state table if it does not exist."""
    conn.executescript(_CREATE_TABLE)


def compute_module_hash(file_hashes: list[str]) -> str:
    """SHA256 of sorted file hashes — deterministic module fingerprint."""
    combined = "".join(sorted(file_hashes))
    return hashlib.sha256(combined.encode()).hexdigest()


def get_dirty_modules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all modules with status='dirty'."""
    rows = conn.execute(
        "SELECT module_path, wiki_file, last_generated_ts, source_hash, status "
        "FROM wiki_state WHERE status = 'dirty'"
    ).fetchall()
    return [
        {
            "module_path": r[0],
            "wiki_file": r[1],
            "last_generated_ts": r[2],
            "source_hash": r[3],
            "status": r[4],
        }
        for r in rows
    ]


def get_all_modules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all modules from wiki_state."""
    rows = conn.execute(
        "SELECT module_path, wiki_file, last_generated_ts, source_hash, status FROM wiki_state"
    ).fetchall()
    return [
        {
            "module_path": r[0],
            "wiki_file": r[1],
            "last_generated_ts": r[2],
            "source_hash": r[3],
            "status": r[4],
        }
        for r in rows
    ]


def wiki_filename(module_path: str) -> str:
    """Compose the on-disk wiki filename for a module path.

    Strips a trailing ``.md`` from the source module path so docs-only
    projects (where every "module" is itself a markdown file like
    ``README.md`` or ``CHANGELOG.md``) don't end up with the cosmetic
    ``modules/README.md.md`` double-extension that leaked into INDEX.md
    in v0.8.65 and earlier.

    Path separators are flattened to ``-`` so the wiki dir stays flat.
    """
    safe_name = module_path.replace("/", "-").replace("\\", "-")
    if safe_name.lower().endswith(".md"):
        safe_name = safe_name[:-3]
    return f"modules/{safe_name}.md"


def mark_dirty(conn: sqlite3.Connection, module_path: str, source_hash: str) -> None:
    """Insert or replace a module as dirty."""
    wiki_file = wiki_filename(module_path)
    conn.execute(
        "INSERT OR REPLACE INTO wiki_state (module_path, wiki_file, source_hash, status) "
        "VALUES (?, ?, ?, 'dirty')",
        (module_path, wiki_file, source_hash),
    )


def mark_current(
    conn: sqlite3.Connection,
    module_path: str,
    wiki_file: str,
    source_hash: str,
) -> None:
    """Insert or replace a module as current after successful wiki generation."""
    conn.execute(
        "INSERT OR REPLACE INTO wiki_state "
        "(module_path, wiki_file, source_hash, last_generated_ts, status) "
        "VALUES (?, ?, ?, ?, 'current')",
        (module_path, wiki_file, source_hash, time.time()),
    )


def update_dirty_state(conn: sqlite3.Connection, files: list[Any]) -> int:
    """Group files by module (first 2 path segments), mark dirty if hash changed.

    Each item in *files* must have `.path` and `.content_hash` attributes
    (libs.core.entities.File).

    Returns the number of modules marked dirty.
    """
    # Group files by module
    modules: dict[str, list[str]] = {}
    for f in files:
        parts = f.path.split("/")
        module_path = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        modules.setdefault(module_path, []).append(f.content_hash)

    dirty_count = 0
    for module_path, hashes in modules.items():
        new_hash = compute_module_hash(hashes)

        row = conn.execute(
            "SELECT source_hash FROM wiki_state WHERE module_path = ?",
            (module_path,),
        ).fetchone()

        if row is None or row[0] != new_hash:
            mark_dirty(conn, module_path, new_hash)
            dirty_count += 1

    return dirty_count
