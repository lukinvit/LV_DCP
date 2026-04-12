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


_MANAGED_SECTION = """\

<!-- LV_DCP managed section — do not edit manually -->
## LV_DCP Context Discipline (ОБЯЗАТЕЛЬНО)

**BLOCKING REQUIREMENT:** This project is indexed by LV_DCP. \
You MUST call `lvdcp_pack` BEFORE using Grep, Read, or any file exploration tool. \
This is not optional.

**EVERY task starts with lvdcp_pack:**

- Navigate: `lvdcp_pack(path="{root}", query="your question", mode="navigate")`
- Edit: `lvdcp_pack(path="{root}", query="task description", mode="edit")`

**Why:** The pack returns 2-20 KB of ranked files and symbols in <1 second. \
Without it, you grep-walk the entire repo (~1M+ tokens). The pack is 1000x cheaper \
and already knows the dependency graph.

**After receiving the pack:** Read only the top files from it. Do NOT grep the entire repo.
<!-- end LV_DCP managed section -->
"""

_MANAGED_MARKER = "LV_DCP managed section"


def _ensure_claude_md_section(root: Path) -> None:
    """Add LV_DCP discipline section to project CLAUDE.md if missing."""
    claude_md = root / "CLAUDE.md"
    try:
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        if _MANAGED_MARKER in existing:
            return
        section = _MANAGED_SECTION.format(root=root)
        claude_md.write_text(existing + section, encoding="utf-8")
    except OSError:
        pass


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
    _ensure_claude_md_section(resolved)
