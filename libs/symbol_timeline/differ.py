"""Pure AST-snapshot diff - previous scan crossed with current scan into event stream.

Input: two :class:`AstSnapshot` objects. Output: an ordered iterator of
:class:`TimelineEvent` with ``event_type`` in ``{added, modified, removed, moved}``.

**Rename detection is NOT done here** — the differ only sees symbol identity
by ``symbol_id``. A same-content symbol at a different ``file_path`` is emitted
as ``moved``. Cross-id pairing (real renames) lives in
:mod:`libs.symbol_timeline.rename_detect` and consumes the ``added`` + ``removed``
stream produced here.

This module has zero I/O and no global state — trivially unit-testable.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from libs.symbol_timeline.store import TimelineEvent


@dataclass(frozen=True)
class SymbolSnapshot:
    """One symbol as seen by a single scan."""

    symbol_id: str
    file_path: str
    content_hash: str
    qualified_name: str | None = None


@dataclass(frozen=True)
class AstSnapshot:
    """Collection of symbols from one scan. Keyed by ``symbol_id``."""

    symbols: Mapping[str, SymbolSnapshot]
    commit_sha: str | None = None


def diff_ast_snapshots(
    prev: AstSnapshot,
    curr: AstSnapshot,
    *,
    project_root: str,
    timestamp: float,
    author: str | None = None,
) -> Iterator[TimelineEvent]:
    """Yield events describing the transition ``prev → curr``.

    Rules:
      * symbol in ``curr`` but not ``prev``   → ``added``
      * symbol in ``prev`` but not ``curr``   → ``removed``
      * same id, same content_hash, same file_path → no event (unchanged)
      * same id, same content_hash, different file_path → ``moved``
      * same id, different content_hash       → ``modified``

    The commit_sha stamped on every event is ``curr.commit_sha`` — events are
    always attributed to the commit where the change landed (not the commit
    where the old state lived).
    """
    prev_ids = set(prev.symbols)
    curr_ids = set(curr.symbols)

    # Emit added in deterministic order (sorted by symbol_id) — keeps tests stable.
    for sid in sorted(curr_ids - prev_ids):
        s = curr.symbols[sid]
        yield TimelineEvent(
            project_root=project_root,
            symbol_id=s.symbol_id,
            event_type="added",
            commit_sha=curr.commit_sha,
            timestamp=timestamp,
            author=author,
            content_hash=s.content_hash,
            file_path=s.file_path,
            qualified_name=s.qualified_name,
            extra_json=None,
        )

    # Emit removed using the symbol's last-seen state from prev.
    for sid in sorted(prev_ids - curr_ids):
        s = prev.symbols[sid]
        yield TimelineEvent(
            project_root=project_root,
            symbol_id=s.symbol_id,
            event_type="removed",
            commit_sha=curr.commit_sha,
            timestamp=timestamp,
            author=author,
            content_hash=s.content_hash,
            file_path=s.file_path,
            qualified_name=s.qualified_name,
            extra_json=None,
        )

    # Same id in both — check content and path.
    for sid in sorted(prev_ids & curr_ids):
        prev_s = prev.symbols[sid]
        curr_s = curr.symbols[sid]
        if prev_s.content_hash == curr_s.content_hash:
            if prev_s.file_path == curr_s.file_path:
                continue  # truly unchanged
            # Moved — same content, new path.
            yield TimelineEvent(
                project_root=project_root,
                symbol_id=curr_s.symbol_id,
                event_type="moved",
                commit_sha=curr.commit_sha,
                timestamp=timestamp,
                author=author,
                content_hash=curr_s.content_hash,
                file_path=curr_s.file_path,
                qualified_name=curr_s.qualified_name,
                extra_json=json.dumps({"old_file_path": prev_s.file_path}),
            )
        else:
            yield TimelineEvent(
                project_root=project_root,
                symbol_id=curr_s.symbol_id,
                event_type="modified",
                commit_sha=curr.commit_sha,
                timestamp=timestamp,
                author=author,
                content_hash=curr_s.content_hash,
                file_path=curr_s.file_path,
                qualified_name=curr_s.qualified_name,
                extra_json=json.dumps({"old_content_hash": prev_s.content_hash}),
            )
