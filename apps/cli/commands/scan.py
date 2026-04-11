"""`ctx scan <path>` — walk the project, parse, write .context/ artifacts."""

from __future__ import annotations

from pathlib import Path

import typer
from libs.core.entities import File, Symbol
from libs.core.hashing import content_hash
from libs.core.paths import is_ignored, normalize_path
from libs.dotcontext.writer import write_project_md, write_symbol_index_md
from libs.parsers.registry import detect_language, get_parser
from libs.storage.sqlite_cache import SqliteCache

CACHE_REL = Path(".context") / "cache.db"


def scan(path: Path) -> None:
    """Scan a project and regenerate .context/*.md artifacts."""
    root = path
    cache = SqliteCache(root / CACHE_REL)
    cache.migrate()

    files_processed: list[File] = []
    total_symbols = 0
    total_relations = 0
    all_symbols: list[Symbol] = []

    existing_paths = {f.path for f in cache.iter_files()}
    visited_paths: set[str] = set()

    for abs_path in _walk(root):
        try:
            rel = normalize_path(abs_path, root=root)
        except ValueError:
            continue
        if is_ignored(rel):
            continue

        try:
            data = abs_path.read_bytes()
        except OSError as exc:
            typer.echo(f"skip {rel}: {exc}", err=True)
            continue

        language = detect_language(rel)
        if language == "unknown":
            continue

        parser = get_parser(language)
        if parser is None:
            continue

        parse_result = parser.parse(file_path=rel, data=data)
        if parse_result.errors:
            for err in parse_result.errors:
                typer.echo(f"warn {rel}: {err}", err=True)

        file_entity = File(
            path=rel,
            content_hash=content_hash(data),
            size_bytes=len(data),
            language=language,
            role=parse_result.role,
        )
        cache.put_file(file_entity)
        cache.replace_symbols(file_path=rel, symbols=parse_result.symbols)
        cache.replace_relations(file_path=rel, relations=parse_result.relations)
        visited_paths.add(rel)

        files_processed.append(file_entity)
        all_symbols.extend(parse_result.symbols)
        total_symbols += len(parse_result.symbols)
        total_relations += len(parse_result.relations)

    stale = existing_paths - visited_paths
    for stale_path in stale:
        cache.delete_file(stale_path)

    write_project_md(
        project_root=root,
        project_name=root.name,
        files=files_processed,
        total_symbols=total_symbols,
        total_relations=total_relations,
    )
    write_symbol_index_md(project_root=root, symbols=all_symbols)

    typer.echo(
        f"scanned {len(files_processed)} files, "
        f"{total_symbols} symbols, {total_relations} relations"
    )
    cache.close()


def _walk(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return out
