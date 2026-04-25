"""`ctx memory {list,accept,reject}` — review queue for proposed project memories."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from libs.memory.models import Memory, MemoryStatus
from libs.memory.store import (
    MemoryNotFoundError,
    accept_memory,
    list_memories,
    reject_memory,
)

app = typer.Typer(help="Review reviewable memory entries for a project.")


def _resolve_project(project: Path | None) -> Path:
    return (project or Path.cwd()).resolve()


def _memory_to_json(memory: Memory) -> dict[str, object]:
    """Build the per-row JSON payload for `ctx memory list --json`.

    Schema is a 1:1 mirror of the `Memory` dataclass minus the markdown
    `body` — `body` can be arbitrarily large and is recoverable by
    `cat $(jq -r '.[].path')` if a script actually needs it. Keeping the
    list payload lean lets `ctx memory list --json | jq length` stay
    cheap on projects with hundreds of memories.

    `tags` is a JSON array (not a tuple) for downstream serializers.
    """
    return {
        "id": memory.id,
        "status": memory.status.value,
        "topic": memory.topic,
        "tags": list(memory.tags),
        "created_at_iso": memory.created_at_iso,
        "created_by": memory.created_by,
        "path": memory.path,
    }


@app.command("list")
def list_cmd(
    project: Path | None = typer.Option(  # noqa: B008
        None,
        "--project",
        "-p",
        help="Project root (defaults to cwd).",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter by status: proposed, accepted, or rejected.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a JSON array of memory entries instead of the human-readable "
            "table. Each entry mirrors the `Memory` dataclass minus `body` "
            "(recoverable via `cat $(jq -r '.[].path')`). Empty list (`[]`) "
            "when no memories match — never `null` and never the `(no memories)` "
            "prose marker. Composes with --status."
        ),
    ),
) -> None:
    """List reviewable memories under <project>/.context/memory/."""
    root = _resolve_project(project)
    status_enum = MemoryStatus(status) if status else None
    memories = list_memories(root, status=status_enum)

    if as_json:
        # Bare array, not `{"memories": [...]}` — matches v0.8.41 `restore --json`
        # precedent and the standard `jq` pipeline pattern. An empty list (`[]`)
        # is the contract for "no memories matched"; consumers do
        # `jq length` without a None-guard.
        typer.echo(json.dumps([_memory_to_json(m) for m in memories], indent=2))
        return

    if not memories:
        typer.echo("(no memories)")
        return
    for m in memories:
        typer.echo(f"[{m.status.value:8}] {m.id}  {m.topic}  ({m.created_at_iso})")


@app.command("accept")
def accept_cmd(
    memory_id: str = typer.Argument(..., help="Memory id (e.g. mem_abc123)."),
    project: Path | None = typer.Option(  # noqa: B008
        None,
        "--project",
        "-p",
        help="Project root (defaults to cwd).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the accepted Memory as a single JSON object instead of "
            "the human 'accepted: <id>  <topic>' line. Same per-row schema "
            "as v0.8.44 `memory list --json` (mirrors the `Memory` "
            "dataclass minus `body` — recoverable via `cat $(jq -r .path)`). "
            "Pure data on stdout. The post-mutation `status` field round-"
            'trips as `"accepted"` so a script can confirm the state '
            "transition landed without a follow-up `list --json` call. "
            "Same scriptability discipline as v0.8.42-v0.8.56."
        ),
    ),
) -> None:
    """Mark a proposed memory as accepted — it will be surfaced in retrieval."""
    root = _resolve_project(project)
    try:
        updated = accept_memory(root, memory_id)
    except MemoryNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        # Single-object payload — `accept` is a single-result mutation that
        # returns the updated entity. Reuses `_memory_to_json` (cross-surface
        # schema lock with v0.8.44 `memory list --json`); the `status` field
        # post-mutation is `"accepted"` (a `MemoryStatus.ACCEPTED.value`
        # round-trip that confirms the state transition).
        typer.echo(json.dumps(_memory_to_json(updated), indent=2))
        return
    typer.echo(f"accepted: {updated.id}  {updated.topic}")


@app.command("reject")
def reject_cmd(
    memory_id: str = typer.Argument(..., help="Memory id (e.g. mem_abc123)."),
    project: Path | None = typer.Option(  # noqa: B008
        None,
        "--project",
        "-p",
        help="Project root (defaults to cwd).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit the rejected Memory as a single JSON object instead of "
            "the human 'rejected: <id>  <topic>' line. Same per-row schema "
            "as v0.8.44 `memory list --json` and v0.8.57 `memory accept "
            "--json` (mirrors the `Memory` dataclass minus `body` — "
            "recoverable via `cat $(jq -r .path)`). Pure data on stdout. "
            "The post-mutation `status` field round-trips as "
            '`"rejected"` so a script can confirm the state transition '
            "landed without a follow-up `list --json` call. Closes the "
            "memory-review operator surface alongside v0.8.44 (read) and "
            "v0.8.57 (accept). Same scriptability discipline as v0.8.42-"
            "v0.8.57."
        ),
    ),
) -> None:
    """Mark a proposed memory as rejected — it will not surface in retrieval."""
    root = _resolve_project(project)
    try:
        updated = reject_memory(root, memory_id)
    except MemoryNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        # Single-object payload — same shape and discipline as v0.8.57
        # `memory accept --json`. The `status` field post-mutation is
        # `"rejected"` (a `MemoryStatus.REJECTED.value` round-trip that
        # confirms the state transition).
        typer.echo(json.dumps(_memory_to_json(updated), indent=2))
        return
    typer.echo(f"rejected: {updated.id}  {updated.topic}")
