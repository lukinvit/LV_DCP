"""Domain types for the reviewable memory store."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Memory:
    """A single memory entry parsed from a markdown file on disk.

    ``body`` holds the markdown body without frontmatter. ``path`` is the
    absolute path of the on-disk file and is the identity carrier once a
    memory is stored — callers should not construct ``Memory`` values
    directly outside of :mod:`libs.memory.store`.
    """

    id: str
    status: MemoryStatus
    topic: str
    tags: tuple[str, ...]
    created_at_iso: str
    created_by: str
    body: str
    path: str

    def is_accepted(self) -> bool:
        return self.status is MemoryStatus.ACCEPTED
