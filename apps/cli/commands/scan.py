"""`ctx scan <path>` — walk the project, parse, write .context/ artifacts."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Literal

import typer
from libs.scanning.scanner import CACHE_REL, FTS_REL, scan_project

from apps.agent.config import add_project

# Re-exports for backward compatibility with pack/inspect modules
__all__ = ["CACHE_REL", "FTS_REL", "scan"]

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"


def _auto_register(config_path: Path, root: Path) -> None:
    """Register project in config.yaml if not already present."""
    with contextlib.suppress(Exception):
        add_project(config_path, root)


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

    _auto_register(DEFAULT_CONFIG_PATH, resolved)
