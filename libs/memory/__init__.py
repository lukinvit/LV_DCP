"""Reviewable engineering-memory store for LV_DCP.

Agents and humans propose memory entries; a human reviews them before they
are accepted into the retrieval pack. Matches the ByteRover "git-like
reviewable memory" pattern but stays local-first — each memory is a
markdown file under ``<project>/.context/memory/``, so Obsidian sync
and normal diff-review workflows Just Work.

Public API:

- :class:`libs.memory.models.Memory` — immutable value type
- :class:`libs.memory.models.MemoryStatus` — proposed / accepted / rejected
- :func:`libs.memory.store.propose_memory` — write a new ``proposed`` entry
- :func:`libs.memory.store.list_memories` — list, optionally filtered by status
- :func:`libs.memory.store.accept_memory` / :func:`reject_memory` — flip status
"""

from libs.memory.models import Memory, MemoryStatus

__all__ = ["Memory", "MemoryStatus"]
