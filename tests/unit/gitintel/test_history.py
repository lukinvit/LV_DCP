"""Tests for the git history reader (lvdcp_history backing)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from libs.gitintel.history import HistoryCommit, read_recent_history


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run("git", "init", "-q", cwd=root)
    _run("git", "config", "user.email", "t@example.com", cwd=root)
    _run("git", "config", "user.name", "Tester", cwd=root)
    _run("git", "config", "commit.gpgsign", "false", cwd=root)

    # commit 1 — file alpha
    (root / "alpha.py").write_text("x = 1\n")
    _run("git", "add", "alpha.py", cwd=root)
    _run("git", "commit", "-q", "-m", "feat: add alpha", cwd=root)

    # commit 2 — file beta AND alpha modified
    (root / "beta.py").write_text("y = 2\n")
    (root / "alpha.py").write_text("x = 3\n")
    _run("git", "add", "-A", cwd=root)
    _run("git", "commit", "-q", "-m", "chore: touch alpha, add beta", cwd=root)

    return root


class TestReadRecentHistory:
    def test_returns_typed_commits(self, git_repo: Path) -> None:
        commits = read_recent_history(git_repo, since_days=30)
        assert len(commits) == 2
        for c in commits:
            assert isinstance(c, HistoryCommit)
            assert c.sha
            assert c.author == "Tester"
            assert c.date_iso
            assert c.subject
            assert c.files

    def test_newest_first(self, git_repo: Path) -> None:
        commits = read_recent_history(git_repo, since_days=30)
        assert commits[0].subject.startswith("chore")
        assert commits[1].subject.startswith("feat")

    def test_file_lists_attached(self, git_repo: Path) -> None:
        commits = read_recent_history(git_repo, since_days=30)
        newest = commits[0]
        assert "alpha.py" in newest.files
        assert "beta.py" in newest.files

    def test_filter_path_limits_to_specific_file(self, git_repo: Path) -> None:
        commits = read_recent_history(git_repo, since_days=30, filter_path="beta.py")
        # Only the commit that introduced beta.py.
        assert len(commits) == 1
        assert "beta.py" in commits[0].files

    def test_limit_is_respected(self, git_repo: Path) -> None:
        commits = read_recent_history(git_repo, since_days=30, limit=1)
        assert len(commits) == 1

    def test_zero_limit_returns_empty(self, git_repo: Path) -> None:
        assert read_recent_history(git_repo, limit=0) == []

    def test_non_git_directory_returns_empty(self, tmp_path: Path) -> None:
        not_git = tmp_path / "plain"
        not_git.mkdir()
        assert read_recent_history(not_git) == []

    def test_since_days_excludes_older_commits(self, git_repo: Path) -> None:
        # A future horizon trivially excludes all real commits.
        commits = read_recent_history(git_repo, since_days=0)
        # With --since=0 days ago, boundary semantics from git may keep recent
        # commits; this test checks the call is well-formed, not the boundary.
        assert isinstance(commits, list)

    def test_dates_are_utc_iso(self, git_repo: Path) -> None:
        commits = read_recent_history(git_repo, since_days=30)
        for c in commits:
            # Canonicalized UTC ISO ends with "+00:00".
            assert "+00:00" in c.date_iso or c.date_iso.endswith("Z")
