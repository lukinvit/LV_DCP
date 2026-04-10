"""Shared pytest fixtures for LV_DCP unit and integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Absolute path to the LV_DCP repo root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_repo_path(project_root: Path) -> Path:
    """Absolute path to tests/eval/fixtures/sample_repo."""
    return project_root / "tests" / "eval" / "fixtures" / "sample_repo"
