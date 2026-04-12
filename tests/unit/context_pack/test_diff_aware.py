"""Tests for diff-aware edit pack feature."""

from __future__ import annotations

import subprocess
from pathlib import Path

from libs.context_pack.builder import _git_changed_files


def test_detects_uncommitted_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    # Modify a.py (unstaged change)
    (tmp_path / "a.py").write_text("x = 2\n")
    changed = _git_changed_files(tmp_path)
    assert "a.py" in changed


def test_detects_staged_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "a.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    changed = _git_changed_files(tmp_path)
    assert "a.py" in changed


def test_empty_on_clean_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    changed = _git_changed_files(tmp_path)
    assert changed == []


def test_non_git_returns_empty(tmp_path: Path) -> None:
    assert _git_changed_files(tmp_path) == []
