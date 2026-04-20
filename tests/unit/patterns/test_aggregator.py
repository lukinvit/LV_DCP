"""Tests for cross-project pattern aggregation."""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.patterns.aggregator import build_cross_project_patterns
from libs.scanning.scanner import scan_project


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Two tiny projects plus an un-scanned one."""
    # Project A — bot with handlers + models
    a = tmp_path / "project_a"
    (a / "bot" / "handlers").mkdir(parents=True)
    (a / "bot" / "models").mkdir()
    (a / "bot" / "handlers" / "start.py").write_text(
        "import httpx\n\ndef on_start() -> None: ...\n"
    )
    (a / "bot" / "models" / "user.py").write_text("class User: ...\n")
    scan_project(a, mode="full")

    # Project B — also has handlers + models, and also uses httpx
    b = tmp_path / "project_b"
    (b / "bot" / "handlers").mkdir(parents=True)
    (b / "bot" / "models").mkdir()
    (b / "bot" / "handlers" / "stop.py").write_text("import httpx\n\ndef on_stop() -> None: ...\n")
    (b / "bot" / "models" / "order.py").write_text("class Order: ...\n")
    scan_project(b, mode="full")

    # Project C — never indexed
    c = tmp_path / "project_c"
    c.mkdir()
    (c / "main.py").write_text("x = 1\n")

    return a, b, c


def test_build_patterns_finds_shared_directory_leaves(workspace: tuple[Path, Path, Path]) -> None:
    a, b, _ = workspace
    result = build_cross_project_patterns([a, b])
    leaves = {p.name for p in result.structural_patterns}
    # Both projects have bot/handlers and bot/models → those leaves should surface.
    assert "handlers" in leaves
    assert "models" in leaves


def test_unindexed_project_is_reported_in_skipped(workspace: tuple[Path, Path, Path]) -> None:
    a, _, c = workspace
    result = build_cross_project_patterns([a, c])
    skipped_names = {name for name, _ in result.skipped_projects}
    assert "project_c" in skipped_names


def test_empty_input_returns_empty_patterns(tmp_path: Path) -> None:
    result = build_cross_project_patterns([])
    assert result.total_projects == 0
    assert result.dependency_patterns == ()
    assert result.structural_patterns == ()


def test_readonly_connection_does_not_mutate_cache(workspace: tuple[Path, Path, Path]) -> None:
    a, b, _ = workspace
    cache = a / ".context" / "cache.db"
    mtime_before = cache.stat().st_mtime
    build_cross_project_patterns([a, b])
    mtime_after = cache.stat().st_mtime
    # Read-only URI must not touch the database file.
    assert mtime_before == mtime_after
