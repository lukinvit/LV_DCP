"""`ctx pack <path> <query> --mode navigate|edit` — build and print a context pack."""

from __future__ import annotations

from pathlib import Path

import typer
from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.entities import PackMode
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError


def pack(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    query: str = typer.Argument(...),
    mode: PackMode = typer.Option(  # noqa: B008
        PackMode.NAVIGATE,
        "--mode",
        case_sensitive=False,
    ),
    limit: int = typer.Option(10, "--limit"),
) -> None:
    try:
        idx = ProjectIndex.open(path)
    except ProjectNotIndexedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    with idx:
        result = idx.retrieve(query, mode=mode.value, limit=limit)
        builder = build_edit_pack if mode == PackMode.EDIT else build_navigate_pack
        pack_obj = builder(project_slug=path.name, query=query, result=result)
        typer.echo(pack_obj.assembled_markdown)
