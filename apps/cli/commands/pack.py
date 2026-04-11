"""`ctx pack <path> <query> --mode navigate|edit` — build and print a context pack."""

from __future__ import annotations

from pathlib import Path

import typer
from libs.context_pack.builder import build_edit_pack, build_navigate_pack
from libs.core.entities import PackMode
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.retrieval.pipeline import RetrievalPipeline
from libs.storage.sqlite_cache import SqliteCache

from apps.cli.commands.scan import CACHE_REL


def pack(
    path: Path,
    query: str,
    mode: str,
    limit: int,
) -> None:
    """Build a context pack from a query."""
    # Convert mode string to PackMode enum
    try:
        pack_mode = PackMode(mode.lower())
    except ValueError as err:
        typer.echo(f"Invalid mode: {mode}. Use 'navigate' or 'edit'.", err=True)
        raise typer.Exit(1) from err

    cache_path = path / CACHE_REL
    if not cache_path.exists():
        typer.echo(
            f"no cache at {cache_path}. Run `ctx scan {path}` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    cache = SqliteCache(cache_path)
    cache.migrate()

    fts = FtsIndex(path / ".context" / "fts.db")
    fts.create()

    # Rebuild FTS from cache (Phase 1 — no persistent FTS between runs)
    for f in cache.iter_files():
        try:
            content = (path / f.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        fts.index_file(f.path, f"{f.path}\n{content}")

    sym_idx = SymbolIndex()
    sym_idx.extend(list(cache.iter_symbols()))

    pipeline = RetrievalPipeline(cache=cache, fts=fts, symbols=sym_idx)
    result = pipeline.retrieve(query, mode=pack_mode.value, limit=limit)

    if pack_mode == PackMode.EDIT:
        pack_obj = build_edit_pack(
            project_slug=path.name,
            query=query,
            result=result,
        )
    else:
        pack_obj = build_navigate_pack(
            project_slug=path.name,
            query=query,
            result=result,
        )

    typer.echo(pack_obj.assembled_markdown)
    cache.close()
