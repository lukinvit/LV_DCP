"""Shared pytest fixtures for LV_DCP unit and integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from libs.embeddings.adapter import FakeBgeM3Adapter


@pytest.fixture
def project_root() -> Path:
    """Absolute path to the LV_DCP repo root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_repo_path(project_root: Path) -> Path:
    """Absolute path to tests/eval/fixtures/sample_repo."""
    return project_root / "tests" / "eval" / "fixtures" / "sample_repo"


@pytest.fixture
def bge_m3_fake_adapter() -> FakeBgeM3Adapter:
    """Deterministic multi-vector adapter for tests.

    Spec #1 T005 — provides dense + sparse + colbert shapes compatible with
    the bge-m3 wire format without loading the real model.
    """
    return FakeBgeM3Adapter()
