"""Shared pytest fixtures for LV_DCP unit and integration tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Symbol timeline fixtures (spec-010 T002 + T003)
# ---------------------------------------------------------------------------


@dataclass
class GitRepoHelper:
    """Thin helper around a temporary git repo — used by timeline tests."""

    root: Path

    def write(self, relpath: str, content: str) -> Path:
        """Write *content* into ``root/relpath`` (creates parent dirs)."""
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def delete(self, relpath: str) -> None:
        target = self.root / relpath
        if target.exists():
            target.unlink()

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git subcommand in the repo root and return the result."""
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=check,
        )

    def commit(self, message: str) -> str:
        """Stage everything, commit with *message*, return the new HEAD sha."""
        self.run("add", "-A")
        self.run("commit", "-m", message)
        return self.head_sha()

    def tag(self, name: str, sha: str | None = None) -> str:
        """Create (lightweight) tag pointing at ``sha`` or HEAD. Returns the tag target sha."""
        if sha is None:
            self.run("tag", name)
            return self.head_sha()
        self.run("tag", name, sha)
        return sha

    def head_sha(self) -> str:
        result = self.run("rev-parse", "HEAD")
        return result.stdout.strip()


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> GitRepoHelper:
    """Create a fresh git repo inside ``tmp_path`` with deterministic config.

    Usage::

        def test_x(tmp_git_repo):
            tmp_git_repo.write("a.py", "x = 1\\n")
            sha = tmp_git_repo.commit("initial")
            tmp_git_repo.tag("v1")
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    helper = GitRepoHelper(root=repo_root)
    helper.run("init", "-b", "main")
    helper.run("config", "user.email", "timeline-test@example.com")
    helper.run("config", "user.name", "Timeline Test")
    helper.run("config", "commit.gpgsign", "false")
    return helper


@pytest.fixture
def memory_timeline_sink():  # type: ignore[no-untyped-def]
    """Fresh in-memory :class:`MemoryTimelineSink` — inspect via ``sink.events``.

    Imported lazily so tests that never touch the timeline don't pay for
    the library import.
    """
    from libs.symbol_timeline.sinks import MemoryTimelineSink

    return MemoryTimelineSink()
