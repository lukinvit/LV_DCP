"""Path normalization and ignore rules.

Pure, deterministic, no I/O beyond Path resolution.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_IGNORE_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
    "dist/",
    "build/",
    ".next/",
    ".cache/",
    "coverage/",
    ".context/",
)

DEFAULT_IGNORE_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".log",
    ".DS_Store",
)


def normalize_path(absolute: Path, *, root: Path) -> str:
    """Return a POSIX relative path from ``root`` to ``absolute``.

    Raises ``ValueError`` if ``absolute`` is not inside ``root``.
    """
    absolute = absolute.resolve()
    root = root.resolve()
    try:
        rel = absolute.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path {absolute} is outside root {root}") from exc
    return rel.as_posix()


def is_ignored(relative_posix: str) -> bool:
    """Return True if a path should be excluded from scanning."""
    for prefix in DEFAULT_IGNORE_PREFIXES:
        if relative_posix.startswith(prefix):
            return True
        if f"/{prefix}" in relative_posix:
            return True
    return any(relative_posix.endswith(suffix) for suffix in DEFAULT_IGNORE_SUFFIXES)
