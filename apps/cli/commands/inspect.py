"""`ctx inspect <path>` — print index stats for a scanned project."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError


def inspect(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
) -> None:
    try:
        idx = ProjectIndex.open(path)
    except ProjectNotIndexedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    with idx:
        files = list(idx.iter_files())
        symbols = list(idx.iter_symbols())
        relations = list(idx.iter_relations())

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
