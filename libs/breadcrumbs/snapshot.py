"""A1Snapshot generator — git, scan_history, plan, eval state."""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

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
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if out.returncode != 0:
            return ""
        return out.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def _empty_git_state() -> GitState:
    return GitState(
        branch="",
        upstream=None,
        ahead=0,
        behind=0,
        last_commits=[],
        dirty_files=[],
        staged_files=[],
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
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        last_commits=last_commits,
        dirty_files=dirty,
        staged_files=staged,
    )


T = TypeVar("T")

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_PLAN = 300.0
_TTL_SCAN = 300.0
_TTL_EVAL = 1800.0


def _clear_caches() -> None:
    _CACHE.clear()


def _cached(key: str, ttl: float, producer: Callable[[], T]) -> T:  # noqa: UP047
    now = time.time()
    entry = _CACHE.get(key)
    if entry is not None and (now - entry[0]) < ttl:
        return entry[1]  # type: ignore[no-any-return]
    value = producer()
    _CACHE[key] = (now, value)
    return value


@dataclass(frozen=True)
class PlanRef:
    path: Path
    mtime: float
    total_steps: int


@dataclass(frozen=True)
class ScanSummary:
    timestamp: float
    files_scanned: int
    files_reparsed: int
    duration_ms: float
    status: str


@dataclass(frozen=True)
class A1Snapshot:
    git: GitState
    active_plan: PlanRef | None
    last_scan: ScanSummary | None


def collect_active_plan(*, project_root: Path) -> PlanRef | None:
    plans_dir = project_root / "docs" / "superpowers" / "plans"
    key = f"plan:{plans_dir}"

    def producer() -> PlanRef | None:
        if not plans_dir.exists():
            return None
        candidates = [p for p in plans_dir.glob("*.md") if p.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        newest = candidates[0]
        text = newest.read_text(encoding="utf-8", errors="ignore")
        total_steps = sum(1 for line in text.splitlines() if line.startswith("## Step "))
        return PlanRef(path=newest, mtime=newest.stat().st_mtime, total_steps=total_steps)

    return _cached(key, _TTL_PLAN, producer)


def collect_last_scan(*, project_root: Path) -> ScanSummary | None:
    key = f"scan:{project_root}"

    def producer() -> ScanSummary | None:
        try:
            from libs.scan_history.store import ScanHistoryStore, events_since  # noqa: PLC0415
        except ImportError:
            return None
        store = ScanHistoryStore()
        try:
            store.migrate()
            events = events_since(store, project_root=str(project_root), since_ts=0.0)
        except Exception:
            return None
        finally:
            store.close()
        if not events:
            return None
        ev = events[-1]
        return ScanSummary(
            timestamp=ev.timestamp,
            files_scanned=ev.files_scanned,
            files_reparsed=ev.files_reparsed,
            duration_ms=ev.duration_ms,
            status=ev.status,
        )

    return _cached(key, _TTL_SCAN, producer)


def build_a1_snapshot(*, project_root: Path) -> A1Snapshot:
    return A1Snapshot(
        git=collect_git_state(project_root=project_root),
        active_plan=collect_active_plan(project_root=project_root),
        last_scan=collect_last_scan(project_root=project_root),
    )
