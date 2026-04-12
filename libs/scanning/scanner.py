"""Shared project scanner used by CLI, MCP server, and daemon.

Phase 2 supports two modes:
- "full": re-parse every non-ignored file regardless of hash
- "incremental": skip files whose on-disk content_hash matches cache

Stale file detection (paths in cache but not on disk) runs in both modes.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from libs.core.entities import File, Symbol
from libs.core.hashing import content_hash
from libs.core.paths import is_ignored, normalize_path
from libs.core.secrets import contains_secret_pattern
from libs.dotcontext.writer import write_project_md, write_symbol_index_md
from libs.parsers.registry import detect_language, get_parser
from libs.retrieval.fts import FtsIndex
from libs.scan_history.store import (
    ScanEvent,
    ScanHistoryStore,
    append_event,
    resolve_default_store_path,
)
from libs.storage.sqlite_cache import SqliteCache

CACHE_REL = Path(".context") / "cache.db"
FTS_REL = Path(".context") / "fts.db"


@dataclass(frozen=True)
class ScanResult:
    files_scanned: int
    files_reparsed: int
    stale_files_removed: int
    symbols_extracted: int
    relations_reparsed: int
    relations_cached: int
    elapsed_seconds: float


def _process_and_index_files(  # noqa: PLR0912, PLR0915
    root: Path,
    cache: SqliteCache,
    fts: FtsIndex,
    mode: Literal["full", "incremental"],
    only: set[str] | None = None,
) -> tuple[list[File], list[Symbol], int, int, int, set[str]]:
    """Walk files, parse, and index.

    Return (files, symbols, total_symbols, total_relations, files_reparsed, visited).
    """
    files_processed: list[File] = []
    all_symbols: list[Symbol] = []
    total_symbols = 0
    total_relations = 0
    files_reparsed = 0
    visited_paths: set[str] = set()

    for abs_path in _walk(root):
        try:
            rel = normalize_path(abs_path, root=root)
        except ValueError:
            continue
        if is_ignored(rel):
            continue
        if only is not None and rel not in only:
            continue

        try:
            data = abs_path.read_bytes()
        except OSError:
            continue

        # Skip large data dumps (>100KB JSON files pollute FTS with noise)
        if rel.endswith(".json") and len(data) > 100_000:
            continue

        visited_paths.add(rel)

        language = detect_language(rel)
        if language == "unknown":
            continue

        parser = get_parser(language)
        if parser is None:
            continue

        new_hash = content_hash(data)

        if mode == "incremental":
            cached = cache.get_file(rel)
            if cached is not None and cached.content_hash == new_hash:
                # unchanged — still count as scanned but not reparsed
                files_processed.append(cached)
                continue

        parse_result = parser.parse(file_path=rel, data=data)

        # NEW: secret detection (inline for statement count)
        has_secrets = contains_secret_pattern(data)
        file_entity = File(
            path=rel,
            content_hash=new_hash,
            size_bytes=len(data),
            language=language,
            role=parse_result.role,
            has_secrets=has_secrets,
        )
        cache.put_file(file_entity)
        cache.replace_symbols(file_path=rel, symbols=parse_result.symbols)
        cache.replace_relations(file_path=rel, relations=parse_result.relations)

        # FTS: path only if file has secrets, full content otherwise
        if has_secrets:
            fts.index_file(rel, rel)
        else:
            try:
                text = data.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                text = ""
            fts.index_file(rel, f"{rel}\n{text}")

        files_processed.append(file_entity)
        all_symbols.extend(parse_result.symbols)
        total_symbols += len(parse_result.symbols)
        total_relations += len(parse_result.relations)
        files_reparsed += 1

    return (
        files_processed,
        all_symbols,
        total_symbols,
        total_relations,
        files_reparsed,
        visited_paths,
    )


def scan_project(
    root: Path,
    *,
    mode: Literal["full", "incremental"] = "incremental",
    only: set[str] | None = None,
) -> ScanResult:
    """Scan a project and regenerate .context/ artifacts.

    Args:
        root: absolute project root
        mode: "full" ignores content_hash and re-parses every file.
              "incremental" skips files whose on-disk hash matches cache.
        only: if provided, restrict work to this set of POSIX relative paths.
              Used by the daemon to scan a single changed file. Stale-file
              detection is skipped when this is set.
    """
    start = time.perf_counter()
    root = root.resolve()
    cache_path = root / CACHE_REL
    fts_path = root / FTS_REL

    cache = SqliteCache(cache_path)
    fts = FtsIndex(fts_path)
    try:
        cache.migrate()
        fts.create()

        existing_paths: set[str] = (
            set() if only is not None else {f.path for f in cache.iter_files()}
        )

        (
            files_processed,
            _all_symbols,
            total_symbols,
            total_relations,
            files_reparsed,
            visited_paths,
        ) = _process_and_index_files(root, cache, fts, mode, only)

        # Git intelligence (full scans only, whole-project)
        if mode == "full" and only is None:
            from libs.gitintel.extractor import extract_git_stats  # noqa: PLC0415

            git_stats = extract_git_stats(root)
            now_ts = time.time()
            for file_stats in git_stats.values():
                if file_stats.file_path in visited_paths:
                    cache.put_git_stats(file_stats, computed_at=now_ts)

        # Stale file cleanup (only in whole-project scans)
        stale_files_removed = 0
        if only is None:
            stale = existing_paths - visited_paths
            for stale_path in stale:
                cache.delete_file(stale_path)
                fts.delete_file(stale_path)
                stale_files_removed += 1

        # Refresh .context/*.md artifacts
        all_cached_files = list(cache.iter_files())
        all_cached_symbols = list(cache.iter_symbols())
        total_relations_cached = sum(1 for _ in cache.iter_relations())

        write_project_md(
            project_root=root,
            project_name=root.name,
            files=all_cached_files,
            total_symbols=len(all_cached_symbols),
            total_relations=total_relations_cached,
        )
        write_symbol_index_md(project_root=root, symbols=all_cached_symbols)

        elapsed = time.perf_counter() - start
        result = ScanResult(
            files_scanned=len(files_processed),
            files_reparsed=files_reparsed,
            stale_files_removed=stale_files_removed,
            symbols_extracted=total_symbols,
            relations_reparsed=total_relations,
            relations_cached=total_relations_cached,
            elapsed_seconds=elapsed,
        )
        # Only write a history event for whole-project scans (no `only` filter).
        # Daemon-triggered partial scans write their own event via process_pending_events.
        if only is None:
            try:
                history_store = ScanHistoryStore(resolve_default_store_path())
                history_store.migrate()
                append_event(
                    history_store,
                    event=ScanEvent(
                        project_root=str(root),
                        timestamp=time.time(),
                        files_reparsed=result.files_reparsed,
                        files_scanned=result.files_scanned,
                        duration_ms=elapsed * 1000.0,
                        status="ok",
                        source="manual",
                    ),
                )
                history_store.close()
            except (OSError, sqlite3.DatabaseError):
                # Best-effort: history write must never kill a scan.
                pass
        return result
    finally:
        fts.close()
        cache.close()


def _walk(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return out
