"""Pair ``added`` + ``removed`` events into rename edges (spec §Key Entities).

Phase 2 baseline (per research.md R1) uses a hybrid similarity signal:

1. Exact ``content_hash`` match — handled upstream by the differ as ``moved``,
   so we only rarely see it here, but still score 1.0 if present.
2. ``qualified_name`` last-segment exact match — score 0.9 (strong signal:
   same name, new location).
3. ``qualified_name`` fallback through :class:`difflib.SequenceMatcher` ratio
   - continuous 0.0 - 1.0 band.
4. No ``qualified_name`` on either side — score 0.0 (cannot pair).

``is_candidate=True`` for pairs below 1.0 confidence. The scanner keeps both
the original ``added`` and ``removed`` events when ``is_candidate=True`` so
pathological false positives don't silently erase history.

Phase 7 (per plan.md) extends this with ``git log --follow`` as a second
signal; the Protocol stays the same.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from libs.symbol_timeline.store import TimelineEvent


@dataclass(frozen=True)
class RenameEdge:
    """One confirmed (or candidate) rename pair."""

    old_symbol_id: str
    new_symbol_id: str
    confidence: float  # 0.0 .. 1.0
    commit_sha: str | None
    timestamp: float
    is_candidate: bool  # True when confidence < 1.0


def pair_renames(
    events: Iterable[TimelineEvent],
    *,
    similarity_threshold: float = 0.85,
) -> tuple[list[RenameEdge], list[TimelineEvent]]:
    """Pair ``added`` + ``removed`` events into rename edges.

    Returns ``(edges, remaining_events)`` where ``remaining_events`` contains
    every input event unmodified **plus**, for candidate edges (confidence < 1.0),
    the original ``added`` / ``removed`` pair too — so downstream never silently
    loses a removal that might turn out to be spurious.

    For high-confidence edges (1.0), the pair is **consumed** — original
    ``added`` / ``removed`` are dropped from the remaining stream.
    """
    events_list = list(events)
    added = [e for e in events_list if e.event_type == "added"]
    removed = [e for e in events_list if e.event_type == "removed"]
    other = [e for e in events_list if e.event_type not in ("added", "removed")]

    edges: list[RenameEdge] = []
    consumed_added: set[str] = set()
    consumed_removed: set[str] = set()

    # Greedy pairing: for each removed, pick best available added by similarity.
    # Complexity O(|added| * |removed|) — fine for typical scan deltas (< 500).
    for rem in removed:
        best_add: TimelineEvent | None = None
        best_sim: float = 0.0
        for add in added:
            if add.symbol_id in consumed_added:
                continue
            sim = _similarity(rem, add)
            if sim > best_sim:
                best_add, best_sim = add, sim

        if best_add is not None and best_sim >= similarity_threshold:
            is_cand = best_sim < 1.0
            edges.append(
                RenameEdge(
                    old_symbol_id=rem.symbol_id,
                    new_symbol_id=best_add.symbol_id,
                    confidence=best_sim,
                    commit_sha=rem.commit_sha,
                    timestamp=rem.timestamp,
                    is_candidate=is_cand,
                )
            )
            if not is_cand:
                # Full confidence — drop original events.
                consumed_added.add(best_add.symbol_id)
                consumed_removed.add(rem.symbol_id)
            # is_candidate=True: do NOT consume — keep originals in remaining.

    remaining: list[TimelineEvent] = list(other)
    for a in added:
        if a.symbol_id not in consumed_added:
            remaining.append(a)
    for r in removed:
        if r.symbol_id not in consumed_removed:
            remaining.append(r)

    return edges, remaining


def _similarity(removed: TimelineEvent, added: TimelineEvent) -> float:
    """Compute a 0.0-1.0 similarity score between a removed and an added event."""
    # Rare - differ usually catches this as ``moved`` - but still worth a shortcut.
    if removed.content_hash and removed.content_hash == added.content_hash:
        return 1.0

    r_name = removed.qualified_name
    a_name = added.qualified_name
    if r_name is None or a_name is None:
        return 0.0

    r_last = r_name.rsplit(".", 1)[-1]
    a_last = a_name.rsplit(".", 1)[-1]
    if r_last == a_last:
        # Strong signal: same leaf name, different module / file.
        return 0.9

    # Fallback: character-level ratio between the last-segments only.
    # SequenceMatcher.ratio is deterministic and stdlib-only.
    return SequenceMatcher(a=r_last, b=a_last).ratio()
