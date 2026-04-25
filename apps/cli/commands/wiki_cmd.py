"""`ctx wiki update`, `ctx wiki status`, `ctx wiki lint`, `ctx wiki cross-project` subcommands."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import typer
from libs.storage.sqlite_cache import SqliteCache
from libs.wiki.generator import generate_architecture_article, generate_wiki_article
from libs.wiki.index_builder import build_index, write_index
from libs.wiki.state import (
    ensure_wiki_table,
    get_all_modules,
    get_dirty_modules,
    mark_current,
)

app = typer.Typer(name="wiki", help="Wiki knowledge module commands")


@app.command("update")
def update(  # noqa: PLR0912, PLR0915
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

        modules = get_all_modules(conn) if all_modules else get_dirty_modules(conn)

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
                fp for fp in all_files if fp.startswith(module_path + "/") or fp == module_path
            ]

            # Symbols in this module
            mod_symbols = [s.fq_name for s in all_symbols if s.file_path in mod_files]

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

        # Architecture page: generate if missing or >30% modules newly generated
        architecture_path = wiki_dir / "architecture.md"
        generated_count = len(modules)
        total_count = len(get_all_modules(conn))
        should_generate_arch = not architecture_path.exists() or (
            total_count > 0 and generated_count / total_count > 0.30
        )

        if should_generate_arch:
            typer.echo("Generating architecture page...")
            try:
                # Build module summaries from INDEX.md
                index_content = build_index(wiki_dir, project_name)
                module_summaries: dict[str, str] = {}
                for line in index_content.splitlines():
                    m = re.match(r"^- \[(.+?)\]\(.+?\)(?:\s*—\s*(.*))?$", line)
                    if m:
                        module_summaries[m.group(1)] = m.group(2) or ""

                # Collect top 20 inter-module dependencies
                top_deps: list[tuple[str, str]] = []
                for r in all_relations:
                    src_parts = r.src_ref.split("/")
                    dst_parts = r.dst_ref.split("/")
                    src_mod = "/".join(src_parts[:2]) if len(src_parts) >= 2 else src_parts[0]
                    dst_mod = "/".join(dst_parts[:2]) if len(dst_parts) >= 2 else dst_parts[0]
                    if src_mod != dst_mod:
                        pair = (src_mod, dst_mod)
                        if pair not in top_deps:
                            top_deps.append(pair)
                        if len(top_deps) >= 20:
                            break

                arch_content = generate_architecture_article(
                    project_root=project_path,
                    project_name=project_name,
                    module_summaries=module_summaries,
                    top_dependencies=top_deps,
                )
                architecture_path.write_text(arch_content, encoding="utf-8")
                typer.echo(f"  Saved: {architecture_path.relative_to(project_path)}")
            except Exception as exc:
                typer.echo(f"  Architecture generation error: {exc}", err=True)

        # Rebuild INDEX.md
        write_index(wiki_dir, project_name)
        typer.echo(f"Index rebuilt: {wiki_dir / 'INDEX.md'}")


def _module_to_json(mod: dict[str, Any]) -> dict[str, object]:
    """Build the per-row JSON payload for `ctx wiki status --json`.

    Schema is a pass-through of the keys returned by
    :func:`libs.wiki.state.get_all_modules`. `last_generated_ts` is the
    raw POSIX float — the human-readable formatted timestamp the text
    view shows is trivially recoverable via
    `jq -r '.[].last_generated_ts | strftime(...)'` or
    `date -r $(...)`. Keeping the JSON unprocessed lets dashboards do
    age math (`now - last_generated_ts`) without having to parse a
    formatted string back to epoch seconds.
    """
    return {
        "module_path": mod["module_path"],
        "wiki_file": mod["wiki_file"],
        "status": mod["status"],
        "last_generated_ts": mod["last_generated_ts"],
        "source_hash": mod["source_hash"],
    }


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
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a JSON array of wiki module rows instead of the "
            "human-readable table. Each row mirrors the `wiki_state` "
            "row schema: `module_path`, `wiki_file`, `status` "
            "(`dirty` / `current`), `last_generated_ts` (raw POSIX "
            "float — recoverable to a formatted string via "
            "`jq -r '.last_generated_ts | strftime(...)'`), "
            "`source_hash`. Empty list (`[]`) when no modules are "
            "tracked — never `null` and never the prose marker. "
            "Missing `cache.db` still surfaces error on stderr + exit "
            "1 in both modes."
        ),
    ),
) -> None:
    """Show wiki state per module (dirty/current)."""
    db_path = project_path / ".context" / "cache.db"
    if not db_path.exists():
        # Discipline shared with v0.8.42-v0.8.45: --json never swallows
        # the error into a `{"error": "..."}` stdout payload. Scripts
        # gate on exit code (`set -e`); stderr carries the human msg.
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

    if as_json:
        typer.echo(json.dumps([_module_to_json(m) for m in modules], indent=2))
        return

    if not modules:
        typer.echo("No modules tracked.")
        return

    typer.echo(f"{'Module':<40} {'Status':<10} {'Last Generated'}")
    typer.echo("-" * 75)
    for mod in modules:
        ts = mod["last_generated_ts"]
        generated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts > 0 else "never"
        typer.echo(f"{mod['module_path']:<40} {mod['status']:<10} {generated}")


def _issue_to_json(issue: Any) -> dict[str, object]:
    """Build the per-row JSON payload for `ctx wiki lint --json`.

    Schema is a 1:1 mirror of :class:`libs.wiki.lint.LintIssue` — pure
    pass-through of the dataclass fields. Sister-helper to
    `_module_to_json` (v0.8.46) — same pattern of per-row JSON shaping
    in the CLI shell.
    """
    return {
        "severity": issue.severity,
        "module_path": issue.module_path,
        "message": issue.message,
    }


@app.command("lint")
def lint(
    project_path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Path to the scanned project.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help=(
            "Emit a JSON array of lint issues instead of the human-"
            "readable bullet list. Each row mirrors the `LintIssue` "
            "dataclass: `severity` (`error` / `warning`), "
            "`module_path`, `message`. Empty list (`[]`) when no "
            "issues are found — never `null` and never the prose "
            "marker. Exit-code gate carried unchanged in both modes: "
            "any `error`-severity row exits 1 (the script gate "
            "preserved across the render switch); warnings-only exits "
            "0. Same v0.8.42-v0.8.46 discipline — `--json` never "
            'swallows the error into a `{"error": "..."}` stdout '
            "payload."
        ),
    ),
) -> None:
    """Check wiki for orphaned, missing, stale, empty articles and INDEX mismatches."""
    from libs.wiki.lint import lint_wiki  # noqa: PLC0415

    issues = lint_wiki(project_path)
    errors = [i for i in issues if i.severity == "error"]

    if as_json:
        typer.echo(json.dumps([_issue_to_json(i) for i in issues], indent=2))
        # Preserve the v0.8.42-v0.8.46 discipline: the exit-code gate is
        # the script contract — error rows exit 1 in both modes so
        # `set -e` users get the same behavior regardless of `--json`.
        if errors:
            raise typer.Exit(code=1)
        return

    if not issues:
        typer.echo("No issues found.")
        return

    warnings = [i for i in issues if i.severity == "warning"]

    for issue in issues:
        prefix = "ERROR" if issue.severity == "error" else "WARN"
        typer.echo(f"  [{prefix}] {issue.module_path}: {issue.message}")

    typer.echo(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        raise typer.Exit(code=1)


@app.command("cross-project")
def cross_project(
    config_path: Path = typer.Option(  # noqa: B008
        Path.home() / ".lvdcp" / "config.yaml",  # noqa: B008
        "--config",
        help="Path to the global LV_DCP config.",
    ),
) -> None:
    """Generate cross-project wiki from all registered projects."""
    from libs.wiki.cross_project import generate_cross_project_wiki  # noqa: PLC0415

    wiki_dir = Path.home() / ".lvdcp" / "wiki"
    count = generate_cross_project_wiki(config_path, wiki_dir)
    typer.echo(f"Cross-project wiki generated: {count} pattern(s) written to {wiki_dir}")
