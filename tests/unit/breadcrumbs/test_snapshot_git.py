"""Tests for snapshot git state collector."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from libs.breadcrumbs.snapshot import collect_git_state


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    (r / "a.py").write_text("x = 1\n")
    _git(r, "add", "a.py")
    _git(r, "commit", "-q", "-m", "initial")
    return r


def test_collect_git_state_basic(repo: Path) -> None:
    state = collect_git_state(project_root=repo)
    assert state.branch == "main"
    assert state.upstream is None
    assert state.last_commits[0].subject == "initial"


def test_collect_git_state_dirty(repo: Path) -> None:
    (repo / "a.py").write_text("x = 2\n")
    (repo / "b.py").write_text("y = 1\n")
    state = collect_git_state(project_root=repo)
    assert any(f.path == "a.py" for f in state.dirty_files)


def test_collect_git_state_outside_repo(tmp_path: Path) -> None:
    state = collect_git_state(project_root=tmp_path / "not-a-repo")
    assert state.branch == ""
    assert state.last_commits == []
    assert state.dirty_files == []
