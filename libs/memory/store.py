"""Filesystem-backed reviewable memory store.

Layout under the project root::

    <project>/.context/memory/<slug>.md

Each file carries YAML frontmatter (id, status, topic, tags,
created_at, created_by) followed by the markdown body. Frontmatter is
the single source of truth — editing the status field in-place moves a
memory between states, which means Obsidian, GitHub PR review, or a
plain text editor can all be the review UI without extra tooling.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from libs.memory.models import Memory, MemoryStatus

_MEMORY_REL = Path(".context") / "memory"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class MemoryError(Exception):
    """Raised for invalid memory operations (missing frontmatter, bad id, ...)."""


class MemoryNotFoundError(MemoryError):
    """Raised when an operation targets a memory id that is not on disk."""


def _memory_dir(root: Path) -> Path:
    return root / _MEMORY_REL


def _slugify(topic: str) -> str:
    base = _SLUG_RE.sub("-", topic.lower()).strip("-")
    return base or "memory"


def _render(memory: Memory) -> str:
    frontmatter = {
        "id": memory.id,
        "status": memory.status.value,
        "topic": memory.topic,
        "tags": list(memory.tags),
        "created_at": memory.created_at_iso,
        "created_by": memory.created_by,
    }
    header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{header}\n---\n{memory.body.rstrip()}\n"


def _parse(path: Path) -> Memory:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise MemoryError(f"missing YAML frontmatter: {path}")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise MemoryError(f"frontmatter must be a mapping: {path}")
    try:
        status = MemoryStatus(meta["status"])
    except (KeyError, ValueError) as exc:
        raise MemoryError(f"invalid or missing status in {path}: {exc}") from exc
    body = match.group(2)
    tags_raw = meta.get("tags") or []
    if not isinstance(tags_raw, list):
        raise MemoryError(f"tags must be a list in {path}")
    return Memory(
        id=str(meta.get("id") or ""),
        status=status,
        topic=str(meta.get("topic") or ""),
        tags=tuple(str(t) for t in tags_raw),
        created_at_iso=str(meta.get("created_at") or ""),
        created_by=str(meta.get("created_by") or ""),
        body=body,
        path=str(path),
    )


def propose_memory(
    root: Path,
    *,
    topic: str,
    body: str,
    tags: list[str] | None = None,
    created_by: str = "agent",
) -> Memory:
    """Write a new ``proposed`` memory under ``<root>/.context/memory/``.

    The filename is ``<YYYY-MM-DD>-<slug>.md``. The memory's stable id is
    a short UUID — callers should refer to memories by id, not path.
    """
    if not topic.strip():
        raise MemoryError("topic must be non-empty")
    if not body.strip():
        raise MemoryError("body must be non-empty")

    now = datetime.now(tz=UTC)
    memory = Memory(
        id=f"mem_{uuid.uuid4().hex[:10]}",
        status=MemoryStatus.PROPOSED,
        topic=topic.strip(),
        tags=tuple(tags or ()),
        created_at_iso=now.isoformat(),
        created_by=created_by,
        body=body.strip(),
        path="",
    )

    mem_dir = _memory_dir(root)
    mem_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y-%m-%d')}-{_slugify(topic)}-{memory.id[4:10]}.md"
    path = mem_dir / filename

    # Atomic write — write to .tmp, then rename. Prevents half-written
    # frontmatter on crash.
    tmp = path.with_suffix(".md.tmp")
    # Replace the placeholder path with the real one before rendering.
    stored = Memory(
        id=memory.id,
        status=memory.status,
        topic=memory.topic,
        tags=memory.tags,
        created_at_iso=memory.created_at_iso,
        created_by=memory.created_by,
        body=memory.body,
        path=str(path),
    )
    tmp.write_text(_render(stored), encoding="utf-8")
    tmp.replace(path)
    return stored


def list_memories(
    root: Path,
    *,
    status: MemoryStatus | None = None,
) -> list[Memory]:
    """Return every memory on disk, newest-first, optionally filtered by status."""
    mem_dir = _memory_dir(root)
    if not mem_dir.exists():
        return []
    memories: list[Memory] = []
    for p in mem_dir.glob("*.md"):
        try:
            memories.append(_parse(p))
        except MemoryError:
            # Skip malformed files — do not fail the whole listing.
            continue
    if status is not None:
        memories = [m for m in memories if m.status is status]
    memories.sort(key=lambda m: m.created_at_iso, reverse=True)
    return memories


def _find(root: Path, memory_id: str) -> Memory:
    for m in list_memories(root):
        if m.id == memory_id:
            return m
    raise MemoryNotFoundError(f"no memory with id {memory_id!r} under {root}")


def _set_status(root: Path, memory_id: str, new_status: MemoryStatus) -> Memory:
    existing = _find(root, memory_id)
    updated = Memory(
        id=existing.id,
        status=new_status,
        topic=existing.topic,
        tags=existing.tags,
        created_at_iso=existing.created_at_iso,
        created_by=existing.created_by,
        body=existing.body,
        path=existing.path,
    )
    Path(existing.path).write_text(_render(updated), encoding="utf-8")
    return updated


def accept_memory(root: Path, memory_id: str) -> Memory:
    return _set_status(root, memory_id, MemoryStatus.ACCEPTED)


def reject_memory(root: Path, memory_id: str) -> Memory:
    return _set_status(root, memory_id, MemoryStatus.REJECTED)
