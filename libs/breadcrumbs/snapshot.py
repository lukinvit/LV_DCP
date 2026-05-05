"""A1Snapshot generator — git, scan_history, plan, eval state."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitRef:
    sha: str
    subject: str
    rel_time: str


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # M | A | D | ??


@dataclass(frozen=True)
class GitState:
    branch: str
    upstream: str | None
    ahead: int
    behind: int
    last_commits: list[CommitRef]
    dirty_files: list[FileChange]
    staged_files: list[FileChange]


def _git(root: Path, *args: str, timeout: float = 2.0) -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=root, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        if out.returncode != 0:
            return ""
        return out.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def _empty_git_state() -> GitState:
    return GitState(
        branch="", upstream=None, ahead=0, behind=0,
        last_commits=[], dirty_files=[], staged_files=[],
    )


def collect_git_state(*, project_root: Path) -> GitState:
    if not project_root.exists():
        return _empty_git_state()
    branch = _git(project_root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not branch:
        return _empty_git_state()
    upstream = _git(project_root, "rev-parse", "--abbrev-ref", "@{u}").strip() or None
    ahead = behind = 0
    if upstream:
        counts = _git(project_root, "rev-list", "--left-right", "--count", "HEAD...@{u}").strip()
        if counts:
            try:
                a, b = counts.split()
                ahead, behind = int(a), int(b)
            except ValueError:
                pass
    last_commits: list[CommitRef] = []
    log_out = _git(project_root, "log", "-5", "--pretty=format:%h%x09%s%x09%cr")
    for line in log_out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            last_commits.append(CommitRef(sha=parts[0], subject=parts[1], rel_time=parts[2]))
    dirty: list[FileChange] = []
    staged: list[FileChange] = []
    porcelain = _git(project_root, "status", "--porcelain=v1")
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        idx, work, path = line[0], line[1], line[3:]
        if idx not in {" ", "?"}:
            staged.append(FileChange(path=path, status=idx))
        if work != " ":
            dirty.append(FileChange(path=path, status=work if work != " " else idx))
    return GitState(
        branch=branch, upstream=upstream, ahead=ahead, behind=behind,
        last_commits=last_commits, dirty_files=dirty, staged_files=staged,
    )
