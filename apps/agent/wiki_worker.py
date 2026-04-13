"""Background wiki update task — runs in ThreadPoolExecutor after daemon scan."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from libs.core.projects_config import WikiConfig
from libs.wiki.generator import generate_wiki_article
from libs.wiki.index_builder import write_index
from libs.wiki.state import ensure_wiki_table, get_dirty_modules, mark_current

log = logging.getLogger(__name__)

_MAX_SYMBOLS = 20


@dataclass(frozen=True)
class _UpdateContext:
    db_path: Path
    wiki_dir: Path
    project_path: Path
    project_name: str
    article_max_tokens: int


def _gather_module_data(
    conn: sqlite3.Connection,
    module_path: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Query files, symbols, deps, and dependents for a module from the cache DB."""
    file_rows = conn.execute(
        "SELECT path FROM files WHERE path LIKE ? OR path = ?",
        (f"{module_path}/%", module_path),
    ).fetchall()
    mod_files = [r[0] for r in file_rows]

    sym_rows = conn.execute(
        "SELECT fq_name FROM symbols WHERE file_path LIKE ? OR file_path = ?",
        (f"{module_path}/%", module_path),
    ).fetchall()
    mod_symbols = [r[0] for r in sym_rows[:_MAX_SYMBOLS]]
    if len(sym_rows) > _MAX_SYMBOLS:
        log.debug("wiki_worker: truncated symbols %s → %d/%d", module_path, _MAX_SYMBOLS, len(sym_rows))

    dep_rows = conn.execute(
        "SELECT DISTINCT dst_ref FROM relations "
        "WHERE src_ref LIKE ? OR src_ref = ?",
        (f"{module_path}/%", module_path),
    ).fetchall()
    deps = sorted({
        "/".join(r[0].split("/")[:2]) if "/" in r[0] else r[0]
        for r in dep_rows
        if not (r[0].startswith(module_path + "/") or r[0] == module_path)
    })

    dep_on_rows = conn.execute(
        "SELECT DISTINCT src_ref FROM relations "
        "WHERE dst_ref LIKE ? OR dst_ref = ?",
        (f"{module_path}/%", module_path),
    ).fetchall()
    dependents = sorted({
        "/".join(r[0].split("/")[:2]) if "/" in r[0] else r[0]
        for r in dep_on_rows
        if not (r[0].startswith(module_path + "/") or r[0] == module_path)
    })

    return mod_files, mod_symbols, deps, dependents


def _process_module(ctx: _UpdateContext, mod: dict[str, object]) -> None:
    """Generate and persist a wiki article for a single module."""
    module_path = str(mod["module_path"])
    source_hash = str(mod["source_hash"])

    conn = sqlite3.connect(str(ctx.db_path))
    try:
        mod_files, mod_symbols, deps, dependents = _gather_module_data(conn, module_path)
    finally:
        conn.close()

    safe_name = module_path.replace("/", "-").replace("\\", "-")
    article_file = ctx.wiki_dir / "modules" / f"{safe_name}.md"
    existing_article = (
        article_file.read_text(encoding="utf-8") if article_file.exists() else ""
    )

    article = generate_wiki_article(
        project_root=ctx.project_path,
        project_name=ctx.project_name,
        module_path=module_path,
        file_list=mod_files,
        symbols=mod_symbols,
        deps=deps,
        dependents=dependents,
        existing_article=existing_article,
        max_tokens=ctx.article_max_tokens,
    )
    article_file.write_text(article, encoding="utf-8")

    conn = sqlite3.connect(str(ctx.db_path))
    try:
        mark_current(conn, module_path, f"modules/{safe_name}.md", source_hash)
        conn.commit()
    finally:
        conn.close()

    log.info("wiki_worker: generated %s / %s", ctx.project_name, module_path)


def run_wiki_update(project_path: Path, config: WikiConfig) -> None:
    """Generate wiki articles for all dirty modules.

    Designed to run in a background thread. Errors per-module are caught
    and logged; remaining modules continue. Never raises.
    """
    db_path = project_path / ".context" / "cache.db"
    if not db_path.exists():
        return

    wiki_dir = project_path / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "modules").mkdir(parents=True, exist_ok=True)
    project_name = project_path.name

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            ensure_wiki_table(conn)
            conn.commit()
            modules = get_dirty_modules(conn)
        finally:
            conn.close()
    except Exception as exc:
        log.warning("wiki_worker: cannot read dirty modules %s: %s", project_path, exc)
        return

    if not modules:
        return

    modules = modules[: config.max_modules_per_run]
    log.info("wiki_worker: updating %d module(s) for %s", len(modules), project_name)

    ctx = _UpdateContext(
        db_path=db_path,
        wiki_dir=wiki_dir,
        project_path=project_path,
        project_name=project_name,
        article_max_tokens=config.article_max_tokens,
    )
    for mod in modules:
        try:
            _process_module(ctx, mod)
        except Exception as exc:
            log.warning(
                "wiki_worker: failed %s / %s: %s",
                project_name,
                mod.get("module_path", "<unknown>"),
                exc,
            )

    try:
        write_index(wiki_dir, project_name)
    except Exception as exc:
        log.warning("wiki_worker: write_index failed for %s: %s", project_name, exc)
