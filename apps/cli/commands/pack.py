"""`ctx pack <path> <query> --mode navigate|edit` — build and print a context pack."""

from __future__ import annotations

import json
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

import typer
from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.entities import PackMode
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError


def _pack_to_json(pack_obj: Any) -> dict[str, object]:
    """Mirror the MCP ``PackResult`` schema 1:1 so CLI and MCP consumers
    bind to one contract.

    Schema (matches ``apps.mcp.tools.PackResult``):
      - ``markdown``: assembled context pack body (the same string the
        text mode prints to stdout)
      - ``trace_id``: retrieval trace ID for ``ctx history`` /
        ``lvdcp_explain`` lookup
      - ``coverage``: one of ``"high"`` / ``"medium"`` / ``"ambiguous"``
      - ``retrieved_files``: ranked list of file paths
      - ``retrieved_symbols``: ranked list of fully-qualified symbol names

    ``retrieved_files`` and ``retrieved_symbols`` are stored on
    ``ContextPack`` as tuples for hashability — converted to lists here
    because JSON has no tuple type.
    """
    return {
        "markdown": pack_obj.assembled_markdown,
        "trace_id": pack_obj.trace_id,
        "coverage": pack_obj.coverage,
        "retrieved_files": list(pack_obj.retrieved_files),
        "retrieved_symbols": list(pack_obj.retrieved_symbols),
    }


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
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a single JSON object mirroring the MCP `lvdcp_pack` "
            "response shape (markdown + trace_id + coverage + "
            "retrieved_files + retrieved_symbols) instead of the "
            "human-readable markdown."
        ),
    ),
) -> None:
    try:
        idx = ProjectIndex.open(path)
    except ProjectNotIndexedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    with idx:
        result = idx.retrieve(query, mode=mode.value, limit=limit)
        # Persist the trace so F1.B sparklines and lvdcp_explain can see
        # CLI-originated queries, not only MCP lvdcp_pack ones.
        trace_with_project = dataclass_replace(result.trace, project=path.name)
        idx.save_trace(trace_with_project)
        if mode == PackMode.EDIT:
            pack_obj = build_edit_pack(
                project_slug=path.name,
                query=query,
                result=result,
                project_root=path,
            )
        else:
            pack_obj = build_navigate_pack(
                project_slug=path.name,
                query=query,
                result=result,
            )

        if as_json:
            typer.echo(json.dumps(_pack_to_json(pack_obj), indent=2))
            return

        typer.echo(pack_obj.assembled_markdown)
