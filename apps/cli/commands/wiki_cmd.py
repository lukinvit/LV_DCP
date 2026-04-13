"""`ctx wiki update` and `ctx wiki status` subcommands."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from libs.storage.sqlite_cache import SqliteCache
from libs.wiki.generator import generate_wiki_article
from libs.wiki.index_builder import write_index
from libs.wiki.state import (
    ensure_wiki_table,
    get_all_modules,
    get_dirty_modules,
    mark_current,
)

app = typer.Typer(name="wiki", help="Wiki knowledge module commands")


@app.command("update")
def update(
    project_path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to the scanned project.",
    ),
    all_modules: bool = typer.Option(
        False,
        "--all",
        help="Regenerate all articles, not just dirty ones.",
    ),
) -> None:
    """Update wiki articles for dirty (or all) modules."""
    db_path = project_path / ".context" / "cache.db"
    if not db_path.exists():
        typer.echo(
            f"error: no cache.db found at {db_path}. Run `ctx scan` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    wiki_dir = project_path / ".context" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "modules").mkdir(parents=True, exist_ok=True)

    project_name = project_path.name

    with SqliteCache(db_path) as cache:
        cache.migrate()
        conn = cache._connect()
        ensure_wiki_table(conn)
        conn.commit()

        if all_modules:
            modules = get_all_modules(conn)
        else:
            modules = get_dirty_modules(conn)

        if not modules:
            typer.echo("No modules to update.")
            return

        typer.echo(f"Updating {len(modules)} module(s)...")

        # Collect file info and symbols from cache
        all_files = {f.path: f for f in cache.iter_files()}
        all_symbols = list(cache.iter_symbols())
        all_relations = list(cache.iter_relations())

        for mod in modules:
            module_path = mod["module_path"]
            typer.echo(f"  Generating: {module_path}")

            # Files in this module
            mod_files = [
                fp for fp in all_files
                if fp.startswith(module_path + "/") or fp == module_path
            ]

            # Symbols in this module
            mod_symbols = [
                s.fq_name for s in all_symbols
                if s.file_path in mod_files
            ]

            # Dependencies and dependents
            mod_file_set = set(mod_files)
            deps: set[str] = set()
            dependents: set[str] = set()
            for r in all_relations:
                if r.src_ref in mod_file_set and r.dst_ref not in mod_file_set:
                    # This module depends on something external
                    parts = r.dst_ref.split("/")
                    dep_mod = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
                    deps.add(dep_mod)
                elif r.dst_ref in mod_file_set and r.src_ref not in mod_file_set:
                    # Something external depends on this module
                    parts = r.src_ref.split("/")
                    dep_mod = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
                    dependents.add(dep_mod)

            # Read existing article
            safe_name = module_path.replace("/", "-").replace("\\", "-")
            article_file = wiki_dir / "modules" / f"{safe_name}.md"
            existing_article = ""
            if article_file.exists():
                existing_article = article_file.read_text(encoding="utf-8")

            try:
                article = generate_wiki_article(
                    project_root=project_path,
                    project_name=project_name,
                    module_path=module_path,
                    file_list=mod_files,
                    symbols=mod_symbols[:20],  # limit to top 20 symbols
                    deps=sorted(deps),
                    dependents=sorted(dependents),
                    existing_article=existing_article,
                )

                article_file.write_text(article, encoding="utf-8")

                wiki_file = f"modules/{safe_name}.md"
                mark_current(conn, module_path, wiki_file, mod["source_hash"])
                conn.commit()
                typer.echo(f"    Saved: {article_file.relative_to(project_path)}")

            except Exception as exc:
                typer.echo(f"    Error: {exc}", err=True)
                continue

        # Rebuild INDEX.md
        write_index(wiki_dir, project_name)
        typer.echo(f"Index rebuilt: {wiki_dir / 'INDEX.md'}")


@app.command("status")
def status(
    project_path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to the scanned project.",
    ),
) -> None:
    """Show wiki state per module (dirty/current)."""
    db_path = project_path / ".context" / "cache.db"
    if not db_path.exists():
        typer.echo(
            f"error: no cache.db found at {db_path}. Run `ctx scan` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    with SqliteCache(db_path) as cache:
        cache.migrate()
        conn = cache._connect()
        ensure_wiki_table(conn)
        conn.commit()

        modules = get_all_modules(conn)

    if not modules:
        typer.echo("No modules tracked.")
        return

    typer.echo(f"{'Module':<40} {'Status':<10} {'Last Generated'}")
    typer.echo("-" * 75)
    for mod in modules:
        ts = mod["last_generated_ts"]
        if ts > 0:
            generated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        else:
            generated = "never"
        typer.echo(f"{mod['module_path']:<40} {mod['status']:<10} {generated}")
