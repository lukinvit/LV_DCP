"""Tests for git intelligence extractor."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from libs.gitintel.extractor import extract_git_stats
from libs.gitintel.models import GitFileStats


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "foo.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "bar.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add bar"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "foo.py").write_text("print('hello world')\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "update foo"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    return tmp_path


class TestExtractGitStats:
    def test_returns_stats_for_tracked_files(self, git_repo: Path) -> None:
        stats = extract_git_stats(git_repo)
        assert "foo.py" in stats
        assert "bar.py" in stats

    def test_commit_count(self, git_repo: Path) -> None:
        stats = extract_git_stats(git_repo)
        assert stats["foo.py"].commit_count == 2
        assert stats["bar.py"].commit_count == 1

    def test_authors(self, git_repo: Path) -> None:
        stats = extract_git_stats(git_repo)
        assert "Test User" in stats["foo.py"].authors
        assert stats["foo.py"].primary_author == "Test User"

    def test_churn_30d(self, git_repo: Path) -> None:
        stats = extract_git_stats(git_repo)
        assert stats["foo.py"].churn_30d >= 2

    def test_non_git_repo_returns_empty(self, tmp_path: Path) -> None:
        assert extract_git_stats(tmp_path) == {}

    def test_returns_git_file_stats_type(self, git_repo: Path) -> None:
        assert isinstance(extract_git_stats(git_repo)["foo.py"], GitFileStats)
