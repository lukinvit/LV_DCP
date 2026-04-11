"""`ctx inspect <path>` — print index stats for a scanned project."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer
from libs.storage.sqlite_cache import SqliteCache

from apps.cli.commands.scan import CACHE_REL


def inspect(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    cache_path = path / CACHE_REL
    if not cache_path.exists():
        typer.echo(f"no cache at {cache_path}. Run `ctx scan {path}` first.", err=True)
        raise typer.Exit(code=1)

    with SqliteCache(cache_path) as cache:
        cache.migrate()

        files = list(cache.iter_files())
        symbols = list(cache.iter_symbols())
        relations = list(cache.iter_relations())

    lang_counts = Counter(f.language for f in files)
    sym_type_counts = Counter(s.symbol_type.value for s in symbols)
    rel_type_counts = Counter(r.relation_type.value for r in relations)

    typer.echo(f"project: {path.name}")
    typer.echo(f"files: {len(files)}")
    for lang, count in lang_counts.most_common():
        typer.echo(f"  {lang}: {count}")
    typer.echo(f"symbols: {len(symbols)}")
    for t, c in sym_type_counts.most_common():
        typer.echo(f"  {t}: {c}")
    typer.echo(f"relations: {len(relations)}")
    for t, c in rel_type_counts.most_common():
        typer.echo(f"  {t}: {c}")
