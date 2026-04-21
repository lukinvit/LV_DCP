"""`ctx memory {list,accept,reject}` — review queue for proposed project memories."""

from __future__ import annotations

from pathlib import Path

import typer
from libs.memory.models import MemoryStatus
from libs.memory.store import (
    MemoryNotFoundError,
    accept_memory,
    list_memories,
    reject_memory,
)

app = typer.Typer(help="Review reviewable memory entries for a project.")


def _resolve_project(project: Path | None) -> Path:
    return (project or Path.cwd()).resolve()


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
) -> None:
    """List reviewable memories under <project>/.context/memory/."""
    root = _resolve_project(project)
    status_enum = MemoryStatus(status) if status else None
    memories = list_memories(root, status=status_enum)
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
) -> None:
    """Mark a proposed memory as accepted — it will be surfaced in retrieval."""
    root = _resolve_project(project)
    try:
        updated = accept_memory(root, memory_id)
    except MemoryNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
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
) -> None:
    """Mark a proposed memory as rejected — it will not surface in retrieval."""
    root = _resolve_project(project)
    try:
        updated = reject_memory(root, memory_id)
    except MemoryNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"rejected: {updated.id}  {updated.topic}")
