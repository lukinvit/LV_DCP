"""`ctx scan <path>` — walk the project, parse, write .context/ artifacts."""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Literal

import typer
from libs.scanning.scanner import CACHE_REL, FTS_REL, scan_project

from apps.agent.config import add_project

# Re-exports for backward compatibility with pack/inspect modules
__all__ = ["CACHE_REL", "FTS_REL", "scan"]

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
log = logging.getLogger(__name__)


_PROJECT_MARKERS = (".git", "pyproject.toml", "package.json", "go.mod", "Cargo.toml")


def _auto_register(config_path: Path, root: Path) -> None:
    """Register project in config.yaml if not already present.

    Only registers directories that look like real projects (contain a
    known project marker like .git, pyproject.toml, etc.). This prevents
    test fixture directories from polluting the config.
    """
    resolved = root.resolve()
    if not any((resolved / marker).exists() for marker in _PROJECT_MARKERS):
        return
    with contextlib.suppress(Exception):
        add_project(config_path, resolved)


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

    # Qdrant / embedding status hint
    try:
        from libs.core.projects_config import load_config as _load_cfg  # noqa: PLC0415

        _cfg = _load_cfg(DEFAULT_CONFIG_PATH)
        if _cfg.qdrant.enabled:
            _key_var = _cfg.embedding.api_key_env_var
            if _cfg.embedding.provider == "openai" and not os.environ.get(_key_var):
                typer.echo(
                    f"⚠ Qdrant enabled but {_key_var} not set — "
                    f"vector embeddings skipped. Set the key in ~/.zshrc or .env",
                    err=True,
                )
            elif _cfg.embedding.provider == "fake":
                typer.echo(
                    "i Qdrant enabled with fake embeddings (for testing). "
                    "Set embedding.provider=openai in ~/.lvdcp/config.yaml for real vectors.",
                    err=True,
                )
    except Exception:
        log.warning("failed to inspect embedding configuration after scan", exc_info=True)

    _auto_register(DEFAULT_CONFIG_PATH, resolved)
    _ensure_claude_md_section(resolved)
