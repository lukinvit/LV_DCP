"""`ctx scan <path>` — walk the project, parse, write .context/ artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer
from libs.scanning.scanner import CACHE_REL, FTS_REL, scan_project

# Re-exports for backward compatibility with pack/inspect modules
__all__ = ["CACHE_REL", "FTS_REL", "scan"]


def scan(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Force a full re-parse of every file, ignoring content hashes.",
    ),
) -> None:
    """Scan a project and regenerate .context/*.md artifacts."""
    mode: Literal["full", "incremental"] = "full" if full else "incremental"
    resolved = path.resolve()
    result = scan_project(resolved, mode=mode)

    typer.echo(
        f"scanned {result.files_scanned} files in {resolved} "
        f"({result.files_reparsed} reparsed, {result.stale_files_removed} stale removed), "
        f"{result.symbols_extracted} symbols, "
        f"{result.relations_reparsed} reparsed / {result.relations_cached} total relations "
        f"in {result.elapsed_seconds:.2f}s"
    )
