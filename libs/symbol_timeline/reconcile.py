"""Reconcile — mark timeline events whose commits no longer exist as orphaned.

Background: `git rebase`, `git commit --amend`, `git gc --prune=now`, and
force-pushes rewrite commit history. The timeline keeps a ``commit_sha``
per event; when the underlying commit is gone, the event is "orphaned"
— still present for audit but excluded from most read-side queries
(``include_orphaned=False`` default).

Strategy:

1. Enumerate every commit currently reachable in the repo via
   ``git rev-list --all --reflog`` — reflog ensures we include
   ancestors of HEAD-before-rebase that are still recoverable.
2. Compare against ``DISTINCT commit_sha`` in
   ``symbol_timeline_events`` for the project.
3. Pass the reachable set to
   :func:`libs.symbol_timeline.store.reconcile_orphaned_events` which
   flips the ``orphaned`` flag for every stale row in one ``UPDATE``.
4. Never delete — spec §FR-009: prune is a separate, explicit operator
   action (``ctx timeline prune``), not a reconcile side-effect.

We report orphaned counts per ``event_type`` so the operator can tell
"a branch was rebased (lots of orphaned added/modified/removed)" apart
from "one amend (one orphaned modified)".

Spec: specs/010-feature-timeline-index/spec.md §FR-009, §Edge Cases.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    reconcile_orphaned_events,
)
from libs.telemetry.timeline_metrics import record_reconcile_orphans

log = structlog.get_logger(__name__)

GitRunner = Callable[[list[str]], str]
"""Pluggable git runner: ``args -> stdout``. Raises on non-zero exit."""


def _default_git_runner(root: Path) -> GitRunner:
    def run(args: list[str]) -> str:
        res = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), *args],  # noqa: S607
            capture_output=True,
            check=True,
            text=True,
            timeout=10.0,
        )
        return res.stdout

    return run


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    """Outcome of a single :func:`reconcile` run."""

    project_root: str
    git_available: bool
    reachable_commit_count: int
    orphaned_newly_flagged: int
    orphaned_by_event_type: dict[str, int] = field(default_factory=dict)


def list_reachable_commits(
    root: Path,
    *,
    git_runner: GitRunner | None = None,
) -> set[str] | None:
    """Return the set of commit SHAs currently reachable in ``root``.

    Combines ``git rev-list --all`` (all refs) with ``git reflog`` (recently
    unreachable-but-recoverable commits). Returns ``None`` if git is
    unreachable so the caller can abort reconcile cleanly instead of
    flagging every event as orphaned.
    """
    runner = git_runner if git_runner is not None else _default_git_runner(root)
    try:
        all_refs = runner(["rev-list", "--all"])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    shas = {line.strip() for line in all_refs.splitlines() if line.strip()}

    try:
        # reflog entries: "<sha> HEAD@{N}: message" — we only need the sha.
        reflog_out = runner(
            ["reflog", "--format=%H", "--all"],
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # reflog is best-effort — a missing reflog shouldn't fail reconcile,
        # it just means we might over-orphan on a pruned repo. Return rev-list
        # set alone.
        return shas
    for line in reflog_out.splitlines():
        sha = line.strip()
        if sha:
            shas.add(sha)
    return shas


def _count_orphans_by_event_type(
    store: SymbolTimelineStore, *, project_root: str
) -> dict[str, int]:
    """Return ``{event_type: orphaned_count}`` for the project."""
    rows = (
        store._connect()
        .execute(
            "SELECT event_type, COUNT(*) FROM symbol_timeline_events "
            "WHERE project_root = ? AND orphaned = 1 "
            "GROUP BY event_type",
            (project_root,),
        )
        .fetchall()
    )
    return {r[0]: r[1] for r in rows}


def reconcile(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    git_root: Path | None = None,
    git_runner: GitRunner | None = None,
) -> ReconcileReport:
    """Mark events with stale ``commit_sha`` as orphaned.

    ``project_root`` — the identity under which events were stored (usually
    ``str(Path(root).resolve())``). ``git_root`` — the filesystem location
    of the actual repo, defaults to ``Path(project_root)``. Separating them
    supports integration tests that move the repo between scan and
    reconcile.

    Idempotent: a second call with no intervening git rewrite flips nothing
    (``orphaned_newly_flagged=0``).
    """
    root = git_root or Path(project_root)
    start = time.perf_counter()
    reachable = list_reachable_commits(root, git_runner=git_runner)
    if reachable is None:
        log.warning(
            "timeline.reconcile.git_unavailable",
            project_root=project_root,
            duration_ms=round((time.perf_counter() - start) * 1000.0, 2),
        )
        return ReconcileReport(
            project_root=project_root,
            git_available=False,
            reachable_commit_count=0,
            orphaned_newly_flagged=0,
            orphaned_by_event_type=_count_orphans_by_event_type(store, project_root=project_root),
        )

    flagged = reconcile_orphaned_events(
        store,
        project_root=project_root,
        known_commit_shas=reachable,
    )
    record_reconcile_orphans(project_root, flagged)
    orphaned_by_type = _count_orphans_by_event_type(store, project_root=project_root)
    log.info(
        "timeline.reconcile.done",
        project_root=project_root,
        reachable_commit_count=len(reachable),
        orphaned_newly_flagged=flagged,
        orphaned_total=sum(orphaned_by_type.values()),
        duration_ms=round((time.perf_counter() - start) * 1000.0, 2),
    )
    return ReconcileReport(
        project_root=project_root,
        git_available=True,
        reachable_commit_count=len(reachable),
        orphaned_newly_flagged=flagged,
        orphaned_by_event_type=orphaned_by_type,
    )


def prune_events(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    older_than_ts: float,
    only_orphaned: bool = True,
) -> int:
    """Permanently delete events older than ``older_than_ts``.

    Operator-only hard delete (spec FR-009). Defaults to orphaned-only so a
    routine ``ctx timeline prune --older-than=90d`` never removes live
    history. Pass ``only_orphaned=False`` to purge non-orphaned history
    too — the caller is expected to confirm explicitly.

    Returns the number of rows actually deleted.
    """
    conn = store._connect()
    query = "DELETE FROM symbol_timeline_events WHERE project_root = ? AND timestamp < ?"
    params: list[object] = [project_root, older_than_ts]
    if only_orphaned:
        query += " AND orphaned = 1"
    cur = conn.execute(query, params)
    conn.commit()
    return cur.rowcount or 0


__all__ = [
    "GitRunner",
    "ReconcileReport",
    "list_reachable_commits",
    "prune_events",
    "reconcile",
]
