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
    ".playwright-mcp/",
    ".superpowers/",
    ".claude/",
    ".cursor/",
    ".github/",
    "docker/",
    "data/",
    "secrets/",
    "credentials/",
)

DEFAULT_IGNORE_FILENAME_EXACT: tuple[str, ...] = (
    "credentials.json",
    "secrets.json",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.override.yml",
    "ruff.toml",
)

# Explicit allow-list for .env.* variants that are safe to index.
ENV_FILENAME_ALLOW: frozenset[str] = frozenset({".env.example"})

DEFAULT_IGNORE_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".log",
    ".DS_Store",
    ".min.js",
    ".min.css",
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


def is_test_path(relative_posix: str) -> bool:
    """Return True if the path belongs to a test file.

    Heuristic covers common test layouts:
    - Any path segment ``tests/`` in the middle or start (e.g. ``app/tests/helper.py``)
    - Path rooted at ``tests/`` (e.g. ``tests/test_foo.py``)
    - File name suffix ``_test.py`` (pytest naming)
    - File name prefix ``test_`` at the root segment (e.g. ``test_bar.py``)

    Note: ``docs/test.md`` returns False because the *file name* ``test.md``
    does not start with ``test_`` and the path does not start with ``tests/``.
    """
    p = relative_posix.replace("\\", "/")
    return (
        "/tests/" in p or p.startswith("tests/") or p.endswith("_test.py") or p.startswith("test_")
    )


def is_ignored(relative_posix: str) -> bool:
    """Return True if a path should be excluded from scanning."""
    for prefix in DEFAULT_IGNORE_PREFIXES:
        if relative_posix.startswith(prefix):
            return True
        if f"/{prefix}" in relative_posix:
            return True
    basename = relative_posix.rsplit("/", 1)[-1]
    if basename in DEFAULT_IGNORE_FILENAME_EXACT:
        return True
    # Any .env or .env.* file is ignored UNLESS explicitly allow-listed.
    if basename == ".env" or (basename.startswith(".env.") and basename not in ENV_FILENAME_ALLOW):
        return True
    return any(relative_posix.endswith(suffix) for suffix in DEFAULT_IGNORE_SUFFIXES)
