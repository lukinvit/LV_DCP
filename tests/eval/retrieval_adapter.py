"""Adapter: glues the eval harness to ProjectIndex-based retrieval."""

from __future__ import annotations

import atexit
from pathlib import Path

from libs.project_index.index import ProjectIndex
from libs.scanning.scanner import scan_project

_cached: tuple[Path, ProjectIndex] | None = None


def _build_for(repo: Path) -> ProjectIndex:
    global _cached
    if _cached is not None and _cached[0] == repo:
        return _cached[1]

    # Always full-scan the fixture (cheap, ~25 files)
    scan_project(repo, mode="full")
    idx = ProjectIndex.open(repo)
    _cached = (repo, idx)
    atexit.register(idx.close)
    return idx


def retrieve_for_eval(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    idx = _build_for(repo)
    result = idx.retrieve(query, mode=mode, limit=10)
    return result.files, result.symbols
