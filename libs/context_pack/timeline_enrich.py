"""Context-pack timeline enrichment (spec-010 T040).

Query-driven addon that injects a small ``## Timeline facts`` section into
``ContextPack.assembled_markdown`` when the user's query asks a timeline-
flavored question ("when was X added?", "что удалили после v1.2",
"history of module.py").

Design:

* :func:`detect_timeline_markers` — regex/keyword scan over the raw query.
  Returns a :class:`TimelineMarkers` bag with the matched *kind* and any
  extracted ref/symbol substring. The scan is cheap (<1 ms) and runs on
  every pack build; the real cost is the downstream timeline query which
  only runs when a marker hits.

* :func:`enrich_pack_with_timeline` — takes an assembled markdown string
  and appends the facts section. The section is capped at
  :data:`_SECTION_SIZE_BUDGET_BYTES` so a noisy repo can never blow the
  15 KB pack budget. When the budget is exceeded we render a truncation
  hint and stop.

Gated by :attr:`libs.core.projects_config.TimelineConfig.enable_timeline_enrichment`.
The enrichment is a read-only side-channel — no DB writes, no git fetches
beyond the ones :mod:`libs.symbol_timeline.query` already performs.

Spec: specs/010-feature-timeline-index/plan.md §Pack enrichment.
"""
# Cyrillic letters in regex patterns are intentional — the file matches
# Russian timeline phrasings verbatim ("удалили", "когда был", "между X и Y").
# ruff: noqa: RUF001

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from libs.symbol_timeline.query import (
    DiffResult,
    RemovedSinceResult,
    SymbolTimelineResult,
    diff,
    find_removed_since,
    symbol_timeline,
)
from libs.symbol_timeline.store import SymbolTimelineStore, resolve_default_store_path

# Hard cap on the injected section — plan.md says ≤ 3 KB.
_SECTION_SIZE_BUDGET_BYTES = 3 * 1024

MarkerKind = Literal["removed_since", "diff", "symbol_history"]


@dataclass(frozen=True, slots=True)
class TimelineMarkers:
    """Outcome of :func:`detect_timeline_markers` — zero or more markers."""

    kinds: tuple[MarkerKind, ...] = ()
    refs: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()

    @property
    def hit(self) -> bool:
        """True when at least one marker matched."""
        return bool(self.kinds)


# ---------------------------------------------------------------------------
# Marker detection.
# ---------------------------------------------------------------------------

# Stem-based keywords, so "removed"/"removal"/"удалили"/"удалён" all match
# without us enumerating every form. Order matters only for tests that assert
# kind precedence (removed > diff > symbol_history).
_REMOVED_PATTERNS = (
    re.compile(r"\bremov(?:ed|al)\b", re.IGNORECASE),
    re.compile(r"\bdelet(?:ed|ion)\b", re.IGNORECASE),
    re.compile(r"\bgone\s+since\b", re.IGNORECASE),
    re.compile(r"\bmissing\s+since\b", re.IGNORECASE),
    re.compile(r"\bудал", re.IGNORECASE),  # удалил/удалили/удалён/удаление/удалять
    re.compile(r"\bпропа[лд]", re.IGNORECASE),  # пропал/пропали/пропадают
)
_DIFF_PATTERNS = (
    re.compile(r"\bbetween\s+\S+\s+and\s+\S+\b", re.IGNORECASE),
    re.compile(r"\bdiff\b", re.IGNORECASE),
    re.compile(r"\bchanged\s+between\b", re.IGNORECASE),
    re.compile(r"\bрегресс", re.IGNORECASE),
    re.compile(r"\bмежду\s+\S+\s+и\s+\S+\b", re.IGNORECASE),
)
_SYMBOL_HISTORY_PATTERNS = (
    re.compile(r"\bwhen\s+was\b", re.IGNORECASE),
    re.compile(r"\bhistory\s+of\b", re.IGNORECASE),
    re.compile(r"\brenamed\s+(?:from|to)\b", re.IGNORECASE),
    re.compile(r"\bпереимен", re.IGNORECASE),
    re.compile(r"\bкогда\s+(?:был|была|добавил|удалил)", re.IGNORECASE),
    re.compile(r"\bистори[яюи]\s+", re.IGNORECASE),
)

# Ref-ish tokens: tags (v1.2, v2.0.0-rc1), short SHAs (>= 7 hex), HEAD, HEAD~n.
_REF_PATTERN = re.compile(
    r"\b(?:"
    r"HEAD(?:~\d+)?|"
    r"v\d+(?:\.\d+){0,3}(?:-[A-Za-z0-9]+)?|"
    r"[0-9a-f]{7,40}"
    r")\b"
)

# Symbol-ish tokens: dotted qualified names or module:symbol forms.
_SYMBOL_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,}")


def detect_timeline_markers(query: str) -> TimelineMarkers:
    """Scan ``query`` for timeline-flavored intents.

    Returns an empty :class:`TimelineMarkers` (``hit == False``) when the
    query is purely architectural / navigation-oriented.
    """
    if not query:
        return TimelineMarkers()

    kinds: list[MarkerKind] = []
    for pat in _REMOVED_PATTERNS:
        if pat.search(query):
            kinds.append("removed_since")
            break
    for pat in _DIFF_PATTERNS:
        if pat.search(query):
            kinds.append("diff")
            break
    for pat in _SYMBOL_HISTORY_PATTERNS:
        if pat.search(query):
            kinds.append("symbol_history")
            break

    if not kinds:
        return TimelineMarkers()

    refs = tuple(dict.fromkeys(_REF_PATTERN.findall(query)))  # preserve order, dedupe
    symbols = tuple(dict.fromkeys(_SYMBOL_PATTERN.findall(query)))
    return TimelineMarkers(kinds=tuple(kinds), refs=refs, symbols=symbols)


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _SectionBuffer:
    """Accumulates markdown lines while enforcing the size budget."""

    lines: list[str] = field(default_factory=list)
    used: int = 0
    truncated: bool = False

    def append(self, line: str) -> bool:
        """Append ``line`` if budget permits. Returns ``False`` if truncated."""
        cost = len(line.encode("utf-8")) + 1  # +1 for newline separator
        if self.used + cost > _SECTION_SIZE_BUDGET_BYTES:
            if not self.truncated:
                self.lines.append("_(timeline enrichment truncated to fit budget)_")
                self.truncated = True
            return False
        self.lines.append(line)
        self.used += cost
        return True


def _render_removed(result: RemovedSinceResult, buf: _SectionBuffer) -> None:
    if result.ref_not_found:
        buf.append(f"- removed since `{result.ref}`: _ref not resolvable_")
        return
    if not result.removed and not result.renamed:
        buf.append(f"- removed since `{result.ref}`: none")
        return
    if result.removed:
        buf.append(f"- removed since `{result.ref}` ({len(result.removed)}):")
        rendered = 0
        for r in result.removed[:5]:
            name = r.qualified_name or r.symbol_id
            sha = r.commit_sha[:8] if r.commit_sha else "no-sha"
            if not buf.append(f"  - `{name}` ({r.file_path}) @ `{sha}`"):
                return
            rendered += 1
        # "more" hint uses the *actual* rendered count — the byte-budget in
        # `buf.append` may have stopped us short of 5, and `result.truncated`
        # only says the query layer capped at its own limit.
        remaining = result.total_before_limit - rendered
        if (result.truncated or rendered < len(result.removed)) and remaining > 0:
            buf.append(f"  - _(+{remaining} more)_")
    if result.renamed:
        buf.append(f"- renamed since `{result.ref}` ({len(result.renamed)}):")
        for rp in result.renamed[:3]:
            old = rp.old_qualified_name or rp.old_symbol_id
            new = rp.new_qualified_name or rp.new_symbol_id
            tag = "candidate" if rp.is_candidate else f"{rp.confidence:.2f}"
            if not buf.append(f"  - `{old}` → `{new}` ({tag})"):
                return


def _render_diff(result: DiffResult, buf: _SectionBuffer) -> None:
    if result.ref_not_found:
        buf.append(f"- diff `{result.from_ref}..{result.to_ref}`: _one or both refs unresolved_")
        return
    buf.append(
        f"- diff `{result.from_ref}..{result.to_ref}`: "
        f"+{result.total_added} / ~{result.total_modified} / -{result.total_removed}"
    )
    for bucket_name, bucket in (
        ("added", result.added),
        ("modified", result.modified),
        ("removed", result.removed),
    ):
        for entry in bucket[:3]:
            name = entry.qualified_name or entry.symbol_id
            sha = entry.commit_sha[:8] if entry.commit_sha else "no-sha"
            if not buf.append(f"  - [{bucket_name}] `{name}` @ `{sha}`"):
                return


def _render_symbol_history(result: SymbolTimelineResult, buf: _SectionBuffer) -> None:
    if result.not_found:
        if result.candidates:
            buf.append(
                f"- symbol `{result.symbol_id}`: no exact match, candidates: "
                + ", ".join(f"`{c.qualified_name or c.symbol_id}`" for c in result.candidates[:3])
            )
        else:
            buf.append(f"- symbol `{result.symbol_id}`: not found in timeline")
        return
    name = result.qualified_name or result.symbol_id
    buf.append(f"- `{name}` — {len(result.events)} events; file `{result.file_path}`")
    # Latest 3 events, newest first.
    for ev in result.events[-3:][::-1]:
        sha = ev.commit_sha[:8] if ev.commit_sha else "no-sha"
        if not buf.append(f"  - {ev.event_type} @ `{sha}`"):
            return
    if result.rename_predecessors or result.rename_successors:
        buf.append(
            f"  - renames: "
            f"{len(result.rename_predecessors)} predecessor(s), "
            f"{len(result.rename_successors)} successor(s)"
        )


def _resolve_symbol_from_markers(markers: TimelineMarkers) -> str | None:
    """Pick the best symbol candidate from the query, or ``None``."""
    if not markers.symbols:
        return None
    # Prefer the longest dotted name — "libs.x.y" is more specific than "x.y".
    return max(markers.symbols, key=len)


def enrich_pack_with_timeline(  # noqa: PLR0913 - keyword-only public API
    pack_markdown: str,
    *,
    project_root: Path,
    query: str,
    markers: TimelineMarkers | None = None,
    store: SymbolTimelineStore | None = None,
    enabled: bool = True,
) -> str:
    """Append a ``## Timeline facts`` section to ``pack_markdown`` when warranted.

    * Returns ``pack_markdown`` unchanged when ``enabled`` is ``False``,
      markers don't hit, or the store is unreachable.
    * Opens a ``SymbolTimelineStore`` lazily — callers that never hit a
      marker pay zero timeline-DB cost.

    ``markers`` may be passed pre-computed so the caller can avoid a second
    regex pass; otherwise it's detected from ``query``.
    """
    if not enabled:
        return pack_markdown

    if markers is None:
        markers = detect_timeline_markers(query)
    if not markers.hit:
        return pack_markdown

    owns_store = store is None
    try:
        if store is None:
            store = SymbolTimelineStore(resolve_default_store_path())
            store.migrate()
    except Exception:
        # Missing / malformed store is a silent skip — pack enrichment must
        # never kill a pack build.
        return pack_markdown

    buf = _SectionBuffer()
    buf.append("")
    buf.append("## Timeline facts")
    buf.append("")

    project_root_str = str(project_root.resolve())

    try:
        if "removed_since" in markers.kinds and markers.refs:
            ref = markers.refs[0]
            removed_result = find_removed_since(
                store,
                project_root=project_root_str,
                ref=ref,
                limit=10,
                git_root=project_root,
            )
            _render_removed(removed_result, buf)

        if "diff" in markers.kinds and len(markers.refs) >= 2:
            diff_result = diff(
                store,
                project_root=project_root_str,
                from_ref=markers.refs[0],
                to_ref=markers.refs[1],
                limit_per_bucket=5,
                git_root=project_root,
            )
            _render_diff(diff_result, buf)

        if "symbol_history" in markers.kinds:
            symbol = _resolve_symbol_from_markers(markers)
            if symbol is not None:
                symbol_result = symbol_timeline(
                    store,
                    project_root=project_root_str,
                    symbol=symbol,
                )
                _render_symbol_history(symbol_result, buf)
    finally:
        if owns_store:
            # Close the store we opened; leave caller-owned stores alone.
            with contextlib.suppress(Exception):
                store.close()

    # No body written after the header? Skip the section entirely.
    if len(buf.lines) <= 3:  # "" + "## Timeline facts" + ""
        return pack_markdown

    suffix = "\n".join(buf.lines)
    # Preserve trailing newline behaviour of the source pack.
    sep = "" if pack_markdown.endswith("\n") else "\n"
    return pack_markdown + sep + suffix + "\n"


__all__ = [
    "MarkerKind",
    "TimelineMarkers",
    "detect_timeline_markers",
    "enrich_pack_with_timeline",
]
