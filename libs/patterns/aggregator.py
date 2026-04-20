"""Aggregate cross-project patterns from every indexed project in the workspace.

Reads each project's ``.context/cache.db`` via a strict read-only SQLite URI
(``mode=ro``) and feeds the extracted dependencies and directories into the
existing detectors in :mod:`libs.patterns.detector`. Projects with no cache
file or an unreadable cache are skipped silently — scanning them is out of
scope for this module, which is deliberately non-invasive.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from libs.core.entities import RelationType
from libs.patterns.detector import (
    PatternEntry,
    detect_dependency_patterns,
    detect_structural_patterns,
)

_CACHE_REL = PurePosixPath(".context") / "cache.db"


@dataclass(frozen=True)
class CrossProjectPatterns:
    """Result of a cross-project pattern scan."""

    total_projects: int
    inspected_projects: tuple[str, ...]
    skipped_projects: tuple[tuple[str, str], ...]  # (name, reason)
    dependency_patterns: tuple[PatternEntry, ...]
    structural_patterns: tuple[PatternEntry, ...]


def build_cross_project_patterns(
    project_roots: list[Path],
    *,
    min_projects: int = 2,
) -> CrossProjectPatterns:
    """Scan every project in *project_roots* and aggregate cross-project patterns.

    *min_projects* controls the detector threshold — a pattern must appear in
    at least this many projects to be reported. The default of 2 mirrors
    :func:`libs.patterns.detector.detect_dependency_patterns`.
    """
    project_deps: dict[str, list[str]] = {}
    project_dirs: dict[str, list[str]] = {}
    inspected: list[str] = []
    skipped: list[tuple[str, str]] = []

    for root in project_roots:
        name = root.name
        cache_path = root / _CACHE_REL
        if not cache_path.exists():
            skipped.append((name, "no cache"))
            continue
        try:
            deps = _extract_imports(cache_path)
            dirs = _extract_dirs(cache_path)
        except sqlite3.Error as exc:
            skipped.append((name, f"sqlite error: {exc}"))
            continue

        if not deps and not dirs:
            # Indexed but empty — nothing to contribute.
            skipped.append((name, "empty index"))
            continue

        project_deps[name] = deps
        project_dirs[name] = dirs
        inspected.append(name)

    dep_patterns = detect_dependency_patterns(project_deps, min_projects=min_projects)
    struct_patterns = detect_structural_patterns(project_dirs, min_projects=min_projects)

    return CrossProjectPatterns(
        total_projects=len(project_roots),
        inspected_projects=tuple(sorted(inspected)),
        skipped_projects=tuple(skipped),
        dependency_patterns=tuple(dep_patterns),
        structural_patterns=tuple(struct_patterns),
    )


def _connect_readonly(cache_path: Path) -> sqlite3.Connection:
    """Open *cache_path* strictly read-only via SQLite URI."""
    # sqlite3.connect with uri=True accepts "file:<path>?mode=ro" for a
    # read-only connection. Absolute paths need a leading slash in the URI.
    uri = f"file:{cache_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _extract_imports(cache_path: Path) -> list[str]:
    """Return distinct dst_ref values for IMPORTS relations."""
    conn = _connect_readonly(cache_path)
    try:
        cur = conn.execute(
            "SELECT DISTINCT dst_ref FROM relations WHERE relation_type = ?",
            (RelationType.IMPORTS.value,),
        )
        return [row[0] for row in cur if row[0]]
    finally:
        conn.close()


def _extract_dirs(cache_path: Path) -> list[str]:
    """Return the parent-directory paths of every file in the index."""
    conn = _connect_readonly(cache_path)
    try:
        cur = conn.execute("SELECT path FROM files")
        dirs: set[str] = set()
        for row in cur:
            parent = PurePosixPath(row[0]).parent.as_posix()
            if parent and parent != ".":
                dirs.add(parent)
        return sorted(dirs)
    finally:
        conn.close()
