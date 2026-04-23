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

import structlog

from libs.symbol_timeline.store import (
    SymbolTimelineStore,
    TimelineEvent,
    events_between,
    events_for_symbol,
)
from libs.telemetry.timeline_metrics import observe_query_latency

if TYPE_CHECKING:
    from collections.abc import Callable

log = structlog.get_logger(__name__)


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
class SymbolCandidate:
    """One fuzzy-match hit for a ``qualified_name`` substring."""

    symbol_id: str
    qualified_name: str | None
    file_path: str
    latest_event_ts: float
    latest_event_type: str


@dataclass(frozen=True, slots=True)
class SymbolTimelineResult:
    """Full result of :func:`symbol_timeline` — one symbol's life."""

    symbol_id: str
    qualified_name: str | None
    file_path: str | None
    events: list[TimelineEvent]
    rename_predecessors: list[RenamePair]
    rename_successors: list[RenamePair]
    not_found: bool
    candidates: list[SymbolCandidate]


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


def commits_after_ref(root: Path, ref_sha: str, *, timeout: float = 5.0) -> set[str] | None:
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
    start = time.perf_counter()
    with observe_query_latency("removed_since"):
        result = _find_removed_since_impl(
            store,
            project_root=project_root,
            ref=ref,
            include_renamed=include_renamed,
            limit=limit,
            now=now,
            git_root=git_root,
            importance_lookup=importance_lookup,
        )
    log.info(
        "timeline.query.removed_since",
        project_root=project_root,
        ref=ref,
        ref_resolved_sha=result.ref_resolved_sha,
        ref_not_found=result.ref_not_found,
        removed_count=len(result.removed),
        renamed_count=len(result.renamed),
        truncated=result.truncated,
        duration_ms=round((time.perf_counter() - start) * 1000.0, 2),
    )
    return result


def _find_removed_since_impl(  # noqa: PLR0913 - mirror of find_removed_since
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

    rename_rows = (
        store._connect()
        .execute(
            "SELECT old_symbol_id, new_symbol_id, commit_sha, timestamp, "
            "confidence, is_candidate "
            "FROM symbol_timeline_rename_edges "
            "WHERE project_root = ? AND timestamp > ? "
            "ORDER BY timestamp DESC, id DESC",
            (project_root, ref_ts),
        )
        .fetchall()
    )
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


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """One symbol changed between ``from_ref`` and ``to_ref``."""

    symbol_id: str
    qualified_name: str | None
    file_path: str
    event_type: str  # added | removed | modified
    at_timestamp: float
    commit_sha: str | None
    author: str | None
    importance: float | None = None


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Full result of :func:`diff` — four ranked lists.

    Spec US3: bounded output ≤ 15 KB; each list is independently limited
    and annotated with ``truncated`` when the caller wants to know there
    was more.
    """

    from_ref: str
    to_ref: str
    from_resolved_sha: str | None
    to_resolved_sha: str | None
    from_resolved_timestamp: float | None
    to_resolved_timestamp: float | None
    ref_not_found: bool
    added: list[DiffEntry]
    removed: list[DiffEntry]
    modified: list[DiffEntry]
    renamed: list[RenamePair]
    total_added: int
    total_removed: int
    total_modified: int
    truncated: bool


def _classify_latest(
    events: list[TimelineEvent],
) -> dict[str, TimelineEvent]:
    """Collapse an event stream to the *latest* event per ``symbol_id``.

    A symbol that was ``added`` and then ``removed`` in the window has
    net-effect ``removed``; ``added → modified → modified`` collapses to
    the most recent ``modified`` (but we still surface the net-effect as
    ``added`` if the first event is ``added`` — see :func:`diff`).
    """
    latest: dict[str, TimelineEvent] = {}
    for ev in events:  # events are chronological from events_between
        latest[ev.symbol_id] = ev
    return latest


def _net_effect(
    events: list[TimelineEvent],
) -> dict[str, tuple[str, TimelineEvent]]:
    """Return ``{symbol_id: (net_effect, latest_event)}``.

    ``net_effect`` is the outward-visible change in the window:

    * ``added``    — first event was ``added`` and last was not ``removed``
    * ``removed``  — last event is ``removed`` (regardless of first)
    * ``modified`` — everything else (existed before, still exists)
    """
    first: dict[str, str] = {}
    last_ev: dict[str, TimelineEvent] = {}
    for ev in events:
        if ev.symbol_id not in first:
            first[ev.symbol_id] = ev.event_type
        last_ev[ev.symbol_id] = ev

    out: dict[str, tuple[str, TimelineEvent]] = {}
    for sid, ev in last_ev.items():
        if ev.event_type == "removed":
            out[sid] = ("removed", ev)
        elif first[sid] == "added":
            out[sid] = ("added", ev)
        else:
            out[sid] = ("modified", ev)
    return out


def diff(  # noqa: PLR0913 - keyword-only query API
    store: SymbolTimelineStore,
    *,
    project_root: str,
    from_ref: str,
    to_ref: str = "HEAD",
    limit_per_bucket: int = 20,
    git_root: Path | None = None,
    importance_lookup: Callable[[str], float | None] | None = None,
) -> DiffResult:
    start = time.perf_counter()
    with observe_query_latency("diff"):
        result = _diff_impl(
            store,
            project_root=project_root,
            from_ref=from_ref,
            to_ref=to_ref,
            limit_per_bucket=limit_per_bucket,
            git_root=git_root,
            importance_lookup=importance_lookup,
        )
    log.info(
        "timeline.query.diff",
        project_root=project_root,
        from_ref=from_ref,
        to_ref=to_ref,
        from_sha=result.from_resolved_sha,
        to_sha=result.to_resolved_sha,
        ref_not_found=result.ref_not_found,
        total_added=result.total_added,
        total_removed=result.total_removed,
        total_modified=result.total_modified,
        renamed_count=len(result.renamed),
        truncated=result.truncated,
        duration_ms=round((time.perf_counter() - start) * 1000.0, 2),
    )
    return result


def _diff_impl(  # noqa: PLR0913, PLR0915, PLR0912 - bucketed output impl
    store: SymbolTimelineStore,
    *,
    project_root: str,
    from_ref: str,
    to_ref: str = "HEAD",
    limit_per_bucket: int = 20,
    git_root: Path | None = None,
    importance_lookup: Callable[[str], float | None] | None = None,
) -> DiffResult:
    """Compute structural diff ``from_ref → to_ref``.

    Resolution:

    * Both refs resolve via :func:`resolve_git_ref`. If either fails we
      short-circuit with ``ref_not_found=True``.
    * Events in the window ``(from_ts, to_ts]`` are precision-filtered by
      ``git rev-list from..to`` when available — same technique as
      :func:`find_removed_since` — so events that happened at ``from`` (or
      outside the range by wall-clock skew) don't leak in.

    Classification:

    * Per-symbol net-effect (see :func:`_net_effect`) bucketed into
      ``added``, ``removed``, ``modified``.
    * Rename edges in the window always surface in ``renamed``. When a
      ``removed`` and its paired ``added`` both fall inside the window
      AND the edge is *confirmed*, they're hidden from the bucketed
      lists so the caller doesn't double-count them.

    Ranking:

    * ``importance_lookup`` (typically PageRank centrality) + recency
      DESC, same policy as :func:`find_removed_since`.
    """
    root = git_root or Path(project_root)
    from_res = resolve_git_ref(root, from_ref)
    to_res = resolve_git_ref(root, to_ref)
    if from_res is None or to_res is None:
        return DiffResult(
            from_ref=from_ref,
            to_ref=to_ref,
            from_resolved_sha=from_res[0] if from_res else None,
            to_resolved_sha=to_res[0] if to_res else None,
            from_resolved_timestamp=from_res[1] if from_res else None,
            to_resolved_timestamp=to_res[1] if to_res else None,
            ref_not_found=True,
            added=[],
            removed=[],
            modified=[],
            renamed=[],
            total_added=0,
            total_removed=0,
            total_modified=0,
            truncated=False,
        )
    from_sha, from_ts = from_res
    to_sha, to_ts = to_res

    if from_sha == to_sha:
        # Identical endpoints — spec US3.2: empty lists, tiny response.
        return DiffResult(
            from_ref=from_ref,
            to_ref=to_ref,
            from_resolved_sha=from_sha,
            to_resolved_sha=to_sha,
            from_resolved_timestamp=from_ts,
            to_resolved_timestamp=to_ts,
            ref_not_found=False,
            added=[],
            removed=[],
            modified=[],
            renamed=[],
            total_added=0,
            total_removed=0,
            total_modified=0,
            truncated=False,
        )

    # Scanner emits events at wall-clock AFTER commit, so event.timestamp is
    # always strictly greater than the commit_sha's own timestamp. Use a
    # generous upper cap (same strategy as ``find_removed_since``) and let
    # the commit_sha precision filter constrain the window to exactly
    # ``from..to``. If we used ``to_ts`` here we'd drop events that belong
    # to ``to_sha`` itself.
    upper = time.time() + 86_400
    events = events_between(
        store,
        project_root=project_root,
        from_ts=from_ts + 1e-6,
        to_ts=upper,
        include_orphaned=False,
    )
    # Precision filter: only keep events whose commit_sha is in from..to set.
    reachable = commits_after_ref(root, from_sha)  # HEAD..from_sha^..HEAD
    # commits_after_ref gives reachable from HEAD; we need reachable from to_sha
    # instead. Fall back to a direct `git rev-list from_sha..to_sha` if HEAD != to.
    if to_sha != _rev_parse_head(root):
        reachable_pair = commits_between(root, from_sha=from_sha, to_sha=to_sha)
        if reachable_pair is not None:
            reachable = reachable_pair
    if reachable is not None:
        events = [e for e in events if e.commit_sha is not None and e.commit_sha in reachable]

    # Gather rename edges in the window for later paired-hiding + display.
    # Upper bound uses the same generous cap as the event query above — the
    # ``reachable`` commit_sha set enforces precision.
    rename_rows = (
        store._connect()
        .execute(
            "SELECT old_symbol_id, new_symbol_id, commit_sha, timestamp, "
            "confidence, is_candidate "
            "FROM symbol_timeline_rename_edges "
            "WHERE project_root = ? AND timestamp > ? AND timestamp <= ? "
            "ORDER BY timestamp DESC, id DESC",
            (project_root, from_ts, upper),
        )
        .fetchall()
    )
    if reachable is not None:
        rename_rows = [r for r in rename_rows if r[2] is not None and r[2] in reachable]

    # Build qualified_name lookup from event stream for display enrichment.
    name_by_sid: dict[str, str | None] = {}
    for ev in events:
        if ev.qualified_name and ev.symbol_id not in name_by_sid:
            name_by_sid[ev.symbol_id] = ev.qualified_name

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
    confirmed_old = {p.old_symbol_id for p in rename_pairs if not p.is_candidate}
    confirmed_new = {p.new_symbol_id for p in rename_pairs if not p.is_candidate}

    classification = _net_effect(events)
    added_entries: list[TimelineEvent] = []
    removed_entries: list[TimelineEvent] = []
    modified_entries: list[TimelineEvent] = []
    for sid, (effect, ev) in classification.items():
        if effect == "added":
            if sid in confirmed_new:
                continue  # paired with a confirmed rename predecessor
            added_entries.append(ev)
        elif effect == "removed":
            if sid in confirmed_old:
                continue  # paired with a confirmed rename successor
            removed_entries.append(ev)
        else:
            modified_entries.append(ev)

    def _rank_key(e: TimelineEvent) -> tuple[float, float]:
        imp = 0.0
        if importance_lookup is not None:
            score = importance_lookup(e.qualified_name or e.file_path)
            if score is not None:
                imp = score
        return (imp, e.timestamp)

    added_entries.sort(key=_rank_key, reverse=True)
    removed_entries.sort(key=_rank_key, reverse=True)
    modified_entries.sort(key=_rank_key, reverse=True)

    total_added = len(added_entries)
    total_removed = len(removed_entries)
    total_modified = len(modified_entries)
    truncated = (
        total_added > limit_per_bucket
        or total_removed > limit_per_bucket
        or total_modified > limit_per_bucket
    )

    def _to_entry(ev: TimelineEvent, net: str) -> DiffEntry:
        importance: float | None = None
        if importance_lookup is not None:
            importance = importance_lookup(ev.qualified_name or ev.file_path)
        return DiffEntry(
            symbol_id=ev.symbol_id,
            qualified_name=ev.qualified_name,
            file_path=ev.file_path,
            event_type=net,
            at_timestamp=ev.timestamp,
            commit_sha=ev.commit_sha,
            author=ev.author,
            importance=importance,
        )

    return DiffResult(
        from_ref=from_ref,
        to_ref=to_ref,
        from_resolved_sha=from_sha,
        to_resolved_sha=to_sha,
        from_resolved_timestamp=from_ts,
        to_resolved_timestamp=to_ts,
        ref_not_found=False,
        added=[_to_entry(e, "added") for e in added_entries[:limit_per_bucket]],
        removed=[_to_entry(e, "removed") for e in removed_entries[:limit_per_bucket]],
        modified=[_to_entry(e, "modified") for e in modified_entries[:limit_per_bucket]],
        renamed=rename_pairs,
        total_added=total_added,
        total_removed=total_removed,
        total_modified=total_modified,
        truncated=truncated,
    )


def _rev_parse_head(root: Path, *, timeout: float = 5.0) -> str | None:
    """Return current HEAD sha or ``None`` if git unavailable."""
    try:
        res = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    sha = res.stdout.strip()
    return sha or None


def commits_between(
    root: Path, *, from_sha: str, to_sha: str, timeout: float = 5.0
) -> set[str] | None:
    """Return ``{commit_sha}`` reachable from ``to_sha`` but not from ``from_sha``.

    Uses ``git rev-list from_sha..to_sha``. Empty set when ``from_sha ==
    to_sha``. Returns ``None`` when git is unreachable so the caller falls
    back to a timestamp-only window.
    """
    try:
        res = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "rev-list", f"{from_sha}..{to_sha}"],  # noqa: S607
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


def _looks_like_symbol_id(s: str) -> bool:
    """True when ``s`` is a 32-hex blob that could be a raw symbol_id (FR-003).

    Used to decide whether to treat the tool's ``symbol`` input as an exact
    id lookup or as a qualified-name substring to fuzzy-resolve.
    """
    if len(s) != 32:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True


def fuzzy_symbol_lookup(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    partial_name: str,
    limit: int = 5,
) -> list[SymbolCandidate]:
    """Return up to ``limit`` candidates whose ``qualified_name`` contains ``partial_name``.

    Matches are case-insensitive substring matches. Candidates are ranked by
    recency of their most recent event (newest first), so a just-renamed
    symbol surfaces above stale ghosts. Only the latest event per
    ``symbol_id`` is returned — the caller (``symbol_timeline``) expands it
    to a full history once the user picks one.
    """
    if not partial_name:
        return []
    # Row per symbol_id with its latest event metadata.
    rows = (
        store._connect()
        .execute(
            "SELECT symbol_id, qualified_name, file_path, MAX(timestamp) AS last_ts, "
            "       ( SELECT event_type FROM symbol_timeline_events e2 "
            "         WHERE e2.project_root = e.project_root "
            "           AND e2.symbol_id = e.symbol_id "
            "         ORDER BY timestamp DESC, id DESC LIMIT 1 ) AS last_type "
            "FROM symbol_timeline_events e "
            "WHERE project_root = ? "
            "  AND qualified_name IS NOT NULL "
            "  AND LOWER(qualified_name) LIKE ? "
            "  AND orphaned = 0 "
            "GROUP BY symbol_id "
            "ORDER BY last_ts DESC "
            "LIMIT ?",
            (project_root, f"%{partial_name.lower()}%", limit),
        )
        .fetchall()
    )
    return [
        SymbolCandidate(
            symbol_id=r[0],
            qualified_name=r[1],
            file_path=r[2],
            latest_event_ts=r[3],
            latest_event_type=r[4],
        )
        for r in rows
    ]


def _rename_pairs_for_symbol(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    symbol_id: str,
    name_by_sid: dict[str, str | None],
) -> tuple[list[RenamePair], list[RenamePair]]:
    """Return ``(predecessors, successors)`` rename pairs touching ``symbol_id``.

    ``predecessors`` = edges where the given symbol is the *new* side — i.e.
    something was renamed *into* it. ``successors`` = edges where it is the
    *old* side — i.e. it was later renamed to a new name.
    """
    preds_rows = (
        store._connect()
        .execute(
            "SELECT old_symbol_id, new_symbol_id, commit_sha, timestamp, "
            "confidence, is_candidate "
            "FROM symbol_timeline_rename_edges "
            "WHERE project_root = ? AND new_symbol_id = ? "
            "ORDER BY timestamp ASC, id ASC",
            (project_root, symbol_id),
        )
        .fetchall()
    )
    succs_rows = (
        store._connect()
        .execute(
            "SELECT old_symbol_id, new_symbol_id, commit_sha, timestamp, "
            "confidence, is_candidate "
            "FROM symbol_timeline_rename_edges "
            "WHERE project_root = ? AND old_symbol_id = ? "
            "ORDER BY timestamp ASC, id ASC",
            (project_root, symbol_id),
        )
        .fetchall()
    )

    def _pair(r: tuple) -> RenamePair:  # type: ignore[type-arg]
        return RenamePair(
            old_symbol_id=r[0],
            new_symbol_id=r[1],
            old_qualified_name=name_by_sid.get(r[0]),
            new_qualified_name=name_by_sid.get(r[1]),
            commit_sha=r[2],
            renamed_at=r[3],
            confidence=r[4],
            is_candidate=bool(r[5]),
        )

    return [_pair(r) for r in preds_rows], [_pair(r) for r in succs_rows]


def _latest_name_file(events: list[TimelineEvent]) -> tuple[str | None, str | None]:
    """Pick the most-recent non-null qualified_name + file_path from events."""
    name: str | None = None
    path: str | None = None
    for ev in reversed(events):  # events are chronological; scan newest-first
        if name is None and ev.qualified_name:
            name = ev.qualified_name
        if path is None and ev.file_path:
            path = ev.file_path
        if name is not None and path is not None:
            break
    return name, path


def symbol_timeline(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    symbol: str,
    include_orphaned: bool = False,
    candidate_limit: int = 5,
) -> SymbolTimelineResult:
    """Return the full event history of one symbol.

    ``symbol`` is either:
      * a 32-hex ``symbol_id`` — exact lookup; or
      * a qualified name (or substring) — we fuzzy-resolve via
        :func:`fuzzy_symbol_lookup`. Exactly one match ⇒ we use it;
        zero or many matches ⇒ return ``not_found=True`` and list
        ``candidates`` for the caller to disambiguate.

    Rename edges touching the resolved symbol are returned separately so the
    caller can show "renamed from/to" context without us duplicating events.
    """
    start = time.perf_counter()
    with observe_query_latency("symbol_timeline"):
        result = _symbol_timeline_impl(
            store,
            project_root=project_root,
            symbol=symbol,
            include_orphaned=include_orphaned,
            candidate_limit=candidate_limit,
        )
    log.info(
        "timeline.query.symbol_timeline",
        project_root=project_root,
        symbol=symbol,
        symbol_id=result.symbol_id,
        not_found=result.not_found,
        event_count=len(result.events),
        predecessor_count=len(result.rename_predecessors),
        successor_count=len(result.rename_successors),
        candidate_count=len(result.candidates),
        duration_ms=round((time.perf_counter() - start) * 1000.0, 2),
    )
    return result


def _symbol_timeline_impl(
    store: SymbolTimelineStore,
    *,
    project_root: str,
    symbol: str,
    include_orphaned: bool = False,
    candidate_limit: int = 5,
) -> SymbolTimelineResult:
    resolved_id: str | None = None
    candidates: list[SymbolCandidate] = []

    if _looks_like_symbol_id(symbol):
        resolved_id = symbol
    else:
        candidates = fuzzy_symbol_lookup(
            store, project_root=project_root, partial_name=symbol, limit=candidate_limit
        )
        if len(candidates) == 1:
            resolved_id = candidates[0].symbol_id
            candidates = []  # a unique match isn't a "candidate"

    if resolved_id is None:
        return SymbolTimelineResult(
            symbol_id=symbol,
            qualified_name=None,
            file_path=None,
            events=[],
            rename_predecessors=[],
            rename_successors=[],
            not_found=True,
            candidates=candidates,
        )

    events = events_for_symbol(
        store,
        project_root=project_root,
        symbol_id=resolved_id,
        include_orphaned=include_orphaned,
    )
    if not events:
        # symbol_id was a direct hash but we have no record of it
        return SymbolTimelineResult(
            symbol_id=resolved_id,
            qualified_name=None,
            file_path=None,
            events=[],
            rename_predecessors=[],
            rename_successors=[],
            not_found=True,
            candidates=candidates,
        )

    qualified_name, file_path = _latest_name_file(events)

    # Build name_by_sid for rename-pair enrichment: the resolved symbol itself
    # plus any sids it's paired with in rename edges.
    name_by_sid: dict[str, str | None] = {resolved_id: qualified_name}
    pred_rows = (
        store._connect()
        .execute(
            "SELECT old_symbol_id FROM symbol_timeline_rename_edges "
            "WHERE project_root = ? AND new_symbol_id = ? ",
            (project_root, resolved_id),
        )
        .fetchall()
    )
    succ_rows = (
        store._connect()
        .execute(
            "SELECT new_symbol_id FROM symbol_timeline_rename_edges "
            "WHERE project_root = ? AND old_symbol_id = ? ",
            (project_root, resolved_id),
        )
        .fetchall()
    )
    paired_sids = {r[0] for r in pred_rows} | {r[0] for r in succ_rows}
    for sid in paired_sids:
        # Look up each paired symbol's latest qualified_name for display.
        paired_events = events_for_symbol(
            store,
            project_root=project_root,
            symbol_id=sid,
            include_orphaned=include_orphaned,
        )
        pname, _ = _latest_name_file(paired_events)
        name_by_sid[sid] = pname

    predecessors, successors = _rename_pairs_for_symbol(
        store,
        project_root=project_root,
        symbol_id=resolved_id,
        name_by_sid=name_by_sid,
    )

    return SymbolTimelineResult(
        symbol_id=resolved_id,
        qualified_name=qualified_name,
        file_path=file_path,
        events=events,
        rename_predecessors=predecessors,
        rename_successors=successors,
        not_found=False,
        candidates=[],
    )


__all__ = [
    "DiffEntry",
    "DiffResult",
    "RemovedSinceResult",
    "RemovedSymbol",
    "RenamePair",
    "SymbolCandidate",
    "SymbolTimelineResult",
    "commits_after_ref",
    "commits_between",
    "diff",
    "find_removed_since",
    "fuzzy_symbol_lookup",
    "resolve_git_ref",
    "symbol_timeline",
]
