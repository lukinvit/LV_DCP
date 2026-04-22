"""Git tag watcher — fires when a new (or re-created) tag appears in a repo.

Polling model. Each tick we ask ``git for-each-ref refs/tags`` for the
current ``(tag_name, head_sha)`` pairs and compare against a ``known``
set supplied by the caller. The caller owns state: we stay pure so the
function is trivially testable with a mock ``git_runner``.

Two events can fire per tick:

* :class:`TagEvent` with ``kind="created"`` — brand new tag name.
* :class:`TagEvent` with ``kind="moved"``  — same name, different sha
  (delete + re-create at a different commit).

Spec: specs/010-feature-timeline-index/spec.md §FR-005, §Edge Cases.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TagEvent:
    """One tag observed as new or moved this tick."""

    tag: str
    head_sha: str
    kind: str  # "created" | "moved"
    previous_sha: str | None = None


GitRunner = Callable[[list[str]], str]
"""Pluggable git runner: ``args -> stdout``. Raises on non-zero exit."""


def _default_git_runner(root: Path) -> GitRunner:
    """Return a runner that shells out to ``git -C <root> <args>``."""

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


def list_git_tags(
    root: Path,
    *,
    git_runner: GitRunner | None = None,
) -> dict[str, str]:
    """Return ``{tag_name: head_sha}`` for every tag currently in ``root``.

    Uses ``git for-each-ref --dereference`` so annotated tags resolve to
    their target commit, matching what downstream snapshotting expects.
    Returns an empty dict if git is unreachable — callers treat that as
    "no tags this tick" rather than an error.
    """
    runner = git_runner if git_runner is not None else _default_git_runner(root)
    try:
        raw = runner(
            [
                "for-each-ref",
                "--format=%(refname:short)%09%(objectname)%09%(*objectname)",
                "refs/tags",
            ]
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}
    tags: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2 or not parts[0]:
            continue
        name = parts[0]
        # Columns: refname, refobject, deref-object (empty for lightweight tags)
        obj = parts[2] if len(parts) >= 3 and parts[2] else parts[1]
        if obj:
            tags[name] = obj
    return tags


def poll_tags(
    root: Path,
    known: dict[str, str],
    *,
    git_runner: GitRunner | None = None,
) -> tuple[dict[str, str], list[TagEvent]]:
    """Compare the repo's current tags against ``known``.

    Returns ``(current, events)`` — the caller persists ``current`` as its
    new ``known`` before the next tick. ``events`` contains one entry per
    tag that was created or moved this tick; untouched tags produce
    nothing. Deletions are intentionally NOT emitted — spec treats a
    vanished tag as "snapshot is still valid, just unreferenceable", and
    reconcile handles that separately.
    """
    current = list_git_tags(root, git_runner=git_runner)
    events: list[TagEvent] = []
    for tag, sha in current.items():
        prev = known.get(tag)
        if prev is None:
            events.append(TagEvent(tag=tag, head_sha=sha, kind="created"))
        elif prev != sha:
            events.append(
                TagEvent(tag=tag, head_sha=sha, kind="moved", previous_sha=prev)
            )
    return current, events


__all__ = [
    "GitRunner",
    "TagEvent",
    "list_git_tags",
    "poll_tags",
]
