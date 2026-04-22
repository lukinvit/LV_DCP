"""Timeline read-side queries — powers ``lvdcp_removed_since`` / ``lvdcp_when``.

Pure functions over :class:`SymbolTimelineStore`. The only I/O is a
best-effort ``git`` subprocess to resolve a ref to a commit timestamp; every
query is deterministic given a store snapshot and a ref resolution result.

Spec: specs/010-feature-timeline-index/spec.md §US1.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    events_between,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class RemovedSymbol:
    """One symbol that disappeared after the queried ref."""

    symbol_id: str
    qualified_name: str | None
    file_path: str
    removed_at: float
    commit_sha: str | None
    author: str | None
    importance: float | None


@dataclass(frozen=True, slots=True)
class RenamePair:
    """One rename edge recorded after the queried ref."""

    old_symbol_id: str
    new_symbol_id: str
    old_qualified_name: str | None
    new_qualified_name: str | None
    confidence: float
    is_candidate: bool
    renamed_at: float
    commit_sha: str | None


@dataclass(frozen=True, slots=True)
class RemovedSinceResult:
    """Full result of :func:`find_removed_since`."""

    ref: str
    ref_resolved_sha: str | None
    ref_resolved_timestamp: float | None
    ref_not_found: bool
    removed: list[RemovedSymbol]
    renamed: list[RenamePair]
    total_before_limit: int
    truncated: bool


def commits_after_ref(
    root: Path, ref_sha: str, *, timeout: float = 5.0
) -> set[str] | None:
    """Return the 40-hex shas reachable from ``HEAD`` but not from ``ref_sha``.

    Uses ``git rev-list <ref_sha>..HEAD`` so the set is inclusive of ``HEAD``
    and exclusive of ``ref_sha``. Returns an empty set when ``ref_sha == HEAD``
    (nothing newer than the ref), and ``None`` if git is unreachable so the
    caller can fall back to a timestamp-only filter.
    """
    try:
        res = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "rev-list", f"{ref_sha}..HEAD"],  # noqa: S607
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return {line.strip() for line in res.stdout.splitlines() if line.strip()}


def resolve_git_ref(  # noqa: PLR0911 - each branch returns a distinct sentinel
    root: Path, ref: str, *, timeout: float = 5.0
) -> tuple[str, float] | None:
    """Return ``(commit_sha, unix_timestamp)`` for ``ref`` or ``None`` if unresolvable.

    Wraps two ``git`` subprocess calls: ``rev-parse <ref>^{commit}`` for the
    concrete SHA, then ``log -1 --format=%ct <sha>`` for the commit timestamp.
    Any non-zero exit, timeout, missing git, or parse error returns ``None`` so
    the caller can surface a typed "ref not found" path.
    """
    if not ref:
        return None
    try:
        sha_res = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "rev-parse", f"{ref}^{{commit}}"],  # noqa: S607
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if sha_res.returncode != 0:
        return None
    sha = sha_res.stdout.strip()
    if not sha:
        return None
    try:
        ts_res = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "log", "-1", "--format=%ct", sha],  # noqa: S607
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ts_res.returncode != 0:
        return None
    raw = ts_res.stdout.strip()
    if not raw:
        return None
    try:
        return sha, float(raw)
    except ValueError:
        return None


def find_removed_since(  # noqa: PLR0913 - keyword-only query API
    store: SymbolTimelineStore,
    *,
    project_root: str,
    ref: str,
    include_renamed: bool = False,
    limit: int = 50,
    now: float | None = None,
    git_root: Path | None = None,
    importance_lookup: Callable[[str], float | None] | None = None,
) -> RemovedSinceResult:
    """Return removed symbols after ``ref`` + rename edges for context.

    ``ref`` is resolved to a commit timestamp via ``resolve_git_ref`` in
    ``git_root`` (defaults to ``project_root``). Events with
    ``timestamp > ref_ts`` and ``event_type == "removed"`` are returned,
    ranked by ``(importance_lookup(qualified_name), removed_at)`` DESC.

    When ``include_renamed`` is ``False`` (default), removed events whose
    ``symbol_id`` appears as the old side of a *confirmed* rename edge
    (``is_candidate == False``) are hidden from ``removed`` — those symbols
    didn't truly disappear, they were just given a new name. The edges
    themselves are always returned in ``renamed`` so the caller can explain
    the transformation.
    """
    root = git_root or Path(project_root)
    resolution = resolve_git_ref(root, ref)
    if resolution is None:
        return RemovedSinceResult(
            ref=ref,
            ref_resolved_sha=None,
            ref_resolved_timestamp=None,
            ref_not_found=True,
            removed=[],
            renamed=[],
            total_before_limit=0,
            truncated=False,
        )
    sha, ref_ts = resolution
    upper = now if now is not None else time.time() + 86_400  # generous future cap

    # Strictly after the ref timestamp (the ref's own commit is "before").
    from_ts = ref_ts + 1e-6

    removed_events = events_between(
        store,
        project_root=project_root,
        from_ts=from_ts,
        to_ts=upper,
        event_types=["removed"],
        include_orphaned=False,
    )
    added_events = events_between(
        store,
        project_root=project_root,
        from_ts=from_ts,
        to_ts=upper,
        event_types=["added"],
        include_orphaned=False,
    )

    # Precision filter by commit_sha: scanner emits events at wall-clock time
    # AFTER the commit, so a removal introduced in commit X has timestamp >
    # commit_timestamp(X). Without the sha filter, ``removed_since(v2)`` would
    # leak removals that belong to v2 itself. ``git rev-list ref..HEAD`` gives
    # us the authoritative "strictly after ref" commit set.
    reachable = commits_after_ref(root, sha)
    if reachable is not None:
        removed_events = [
            e for e in removed_events if e.commit_sha is not None and e.commit_sha in reachable
        ]
        added_events = [
            e for e in added_events if e.commit_sha is not None and e.commit_sha in reachable
        ]

    name_by_sid: dict[str, str | None] = {}
    for ev in (*removed_events, *added_events):
        if ev.qualified_name and ev.symbol_id not in name_by_sid:
            name_by_sid[ev.symbol_id] = ev.qualified_name

    rename_rows = store._connect().execute(
        "SELECT old_symbol_id, new_symbol_id, commit_sha, timestamp, "
        "confidence, is_candidate "
        "FROM symbol_timeline_rename_edges "
        "WHERE project_root = ? AND timestamp > ? "
        "ORDER BY timestamp DESC, id DESC",
        (project_root, ref_ts),
    ).fetchall()
    if reachable is not None:
        rename_rows = [r for r in rename_rows if r[2] is not None and r[2] in reachable]
    rename_pairs = [
        RenamePair(
            old_symbol_id=r[0],
            new_symbol_id=r[1],
            old_qualified_name=name_by_sid.get(r[0]),
            new_qualified_name=name_by_sid.get(r[1]),
            commit_sha=r[2],
            renamed_at=r[3],
            confidence=r[4],
            is_candidate=bool(r[5]),
        )
        for r in rename_rows
    ]

    consumed_old_ids = {p.old_symbol_id for p in rename_pairs if not p.is_candidate}
    if not include_renamed:
        removed_events = [e for e in removed_events if e.symbol_id not in consumed_old_ids]

    def _rank_key(e: TimelineEvent) -> tuple[float, float]:
        imp = 0.0
        if importance_lookup is not None:
            score = importance_lookup(e.qualified_name or e.file_path)
            if score is not None:
                imp = score
        return (imp, e.timestamp)

    removed_events.sort(key=_rank_key, reverse=True)
    total_before = len(removed_events)
    truncated = total_before > limit
    removed_events = removed_events[:limit]

    removed_symbols = [
        RemovedSymbol(
            symbol_id=e.symbol_id,
            qualified_name=e.qualified_name,
            file_path=e.file_path,
            removed_at=e.timestamp,
            commit_sha=e.commit_sha,
            author=e.author,
            importance=(
                importance_lookup(e.qualified_name or e.file_path)
                if importance_lookup is not None
                else None
            ),
        )
        for e in removed_events
    ]

    return RemovedSinceResult(
        ref=ref,
        ref_resolved_sha=sha,
        ref_resolved_timestamp=ref_ts,
        ref_not_found=False,
        removed=removed_symbols,
        renamed=rename_pairs,
        total_before_limit=total_before,
        truncated=truncated,
    )


__all__ = [
    "RemovedSinceResult",
    "RemovedSymbol",
    "RenamePair",
    "commits_after_ref",
    "find_removed_since",
    "resolve_git_ref",
]
