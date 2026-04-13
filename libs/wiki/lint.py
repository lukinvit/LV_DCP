"""Deterministic wiki lint checks — no LLM needed."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from libs.wiki.state import ensure_wiki_table, get_all_modules


@dataclass
class LintIssue:
    """A single lint finding."""

    severity: str  # "warning" | "error"
    module_path: str
    message: str


def lint_wiki(project_root: Path) -> list[LintIssue]:  # noqa: PLR0912
    """Run all wiki lint checks and return a list of issues.

    Checks:
    1. Orphaned articles — wiki article exists but module has no files in cache.db
    2. Missing articles — module has files but no wiki article
    3. Stale articles — wiki_state.status = 'dirty'
    4. Empty articles — article file exists but is < 50 bytes
    5. INDEX mismatch — article in modules/ but not in INDEX.md, or vice versa
    """
    issues: list[LintIssue] = []
    db_path = project_root / ".context" / "cache.db"
    wiki_dir = project_root / ".context" / "wiki"
    modules_dir = wiki_dir / "modules"
    index_path = wiki_dir / "INDEX.md"

    if not db_path.exists():
        issues.append(LintIssue("error", "(project)", "No cache.db found. Run `ctx scan` first."))
        return issues

    # Load data from cache.db
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_wiki_table(conn)
        conn.commit()

        # Modules known to wiki_state
        wiki_modules = get_all_modules(conn)

        # Modules that have files in the files table
        file_rows = conn.execute("SELECT DISTINCT path FROM files").fetchall()
    finally:
        conn.close()

    # Build set of modules that have actual files
    modules_with_files: set[str] = set()
    for (path,) in file_rows:
        parts = path.split("/")
        mod = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        modules_with_files.add(mod)

    # Collect article files on disk
    articles_on_disk: set[str] = set()
    if modules_dir.exists():
        for article_path in modules_dir.glob("*.md"):
            articles_on_disk.add(article_path.stem)

    # Helper: module_path -> expected article stem
    def _to_stem(module_path: str) -> str:
        return module_path.replace("/", "-").replace("\\", "-")

    # 1. Orphaned articles — article exists on disk but module has no files
    for stem in articles_on_disk:
        # Find if any module maps to this stem
        has_files = any(_to_stem(mod) == stem for mod in modules_with_files)
        if not has_files:
            issues.append(
                LintIssue(
                    "warning", stem, "Orphaned article: no source files found for this module."
                )
            )

    # 2. Missing articles — module has files but no wiki article on disk
    for mod in modules_with_files:
        stem = _to_stem(mod)
        if stem not in articles_on_disk:
            issues.append(
                LintIssue(
                    "warning", mod, "Missing article: module has source files but no wiki article."
                )
            )

    # 3. Stale articles — status = 'dirty' in wiki_state
    for m in wiki_modules:
        if m["status"] == "dirty":
            issues.append(
                LintIssue(
                    "warning",
                    m["module_path"],
                    "Stale article: source changed since last generation.",
                )
            )

    # 4. Empty articles — file exists but < 50 bytes
    if modules_dir.exists():
        for article_path in modules_dir.glob("*.md"):
            if article_path.stat().st_size < 50:
                issues.append(
                    LintIssue(
                        "error", article_path.stem, "Empty article: file is less than 50 bytes."
                    )
                )

    # 5. INDEX mismatch
    index_entries: set[str] = set()
    if index_path.exists():
        try:
            index_text = index_path.read_text(encoding="utf-8")
        except OSError:
            index_text = ""
        for line in index_text.splitlines():
            match = re.match(r"^- \[(.+?)\]\(modules/.+?\)", line)
            if match:
                index_entries.add(match.group(1))

    # Articles on disk but not in INDEX
    for stem in articles_on_disk:
        if stem not in index_entries:
            issues.append(
                LintIssue(
                    "warning",
                    stem,
                    "INDEX mismatch: article exists in modules/ but not listed in INDEX.md.",
                )
            )

    # Entries in INDEX but no article on disk
    for entry in index_entries:
        if entry not in articles_on_disk:
            issues.append(
                LintIssue(
                    "warning",
                    entry,
                    "INDEX mismatch: listed in INDEX.md but no article file found.",
                )
            )

    return issues
