"""Shared project scanner used by CLI, MCP server, and daemon.

Phase 2 supports two modes:
- "full": re-parse every non-ignored file regardless of hash
- "incremental": skip files whose on-disk content_hash matches cache

Stale file detection (paths in cache but not on disk) runs in both modes.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    files_scanned: int
    files_reparsed: int
    stale_files_removed: int
    symbols_extracted: int
    relations_reparsed: int
    relations_cached: int
    elapsed_seconds: float
    wiki_dirty_count: int = 0  # modules marked dirty in this scan


def _process_and_index_files(  # noqa: PLR0912, PLR0915
    root: Path,
    cache: SqliteCache,
    fts: FtsIndex,
    mode: Literal["full", "incremental"],
    only: set[str] | None = None,
) -> tuple[list[File], list[Symbol], int, int, int, set[str], list[dict[str, Any]]]:
    """Walk files, parse, and index.

    Return (files, symbols, total_symbols, total_relations, files_reparsed, visited, changed_for_embed).
    """
    files_processed: list[File] = []
    all_symbols: list[Symbol] = []
    total_symbols = 0
    total_relations = 0
    files_reparsed = 0
    visited_paths: set[str] = set()
    changed_for_embed: list[dict[str, Any]] = []

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

        # Collect for embedding (non-secret source files only)
        if not has_secrets and language not in ("json", "yaml", "toml"):
            try:
                text = data.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                text = ""
            if text:
                changed_for_embed.append(
                    {
                        "file_path": rel,
                        "content": text,
                        "content_hash": new_hash,
                        "language": language,
                    }
                )

    return (
        files_processed,
        all_symbols,
        total_symbols,
        total_relations,
        files_reparsed,
        visited_paths,
        changed_for_embed,
    )


def scan_project(  # noqa: PLR0912, PLR0915
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
            changed_for_embed,
        ) = _process_and_index_files(root, cache, fts, mode, only)

        # Git intelligence (full scans only, whole-project)
        if mode == "full" and only is None:
            from libs.gitintel.extractor import extract_git_stats  # noqa: PLC0415

            git_stats = extract_git_stats(root)
            now_ts = time.time()
            for file_stats in git_stats.values():
                if file_stats.file_path in visited_paths:
                    cache.put_git_stats(file_stats, computed_at=now_ts)

        # Docs -> code linking (specifies relations)
        from libs.parsers.docs_linker import extract_specifies_relations  # noqa: PLC0415

        docs_files: list[tuple[str, str]] = []
        for f in cache.iter_files():
            if f.role == "docs":
                try:
                    text = (root / f.path).read_text(encoding="utf-8", errors="replace")
                    docs_files.append((f.path, text))
                except OSError:
                    pass
        if docs_files:
            all_paths = {f.path for f in cache.iter_files()}
            spec_rels = extract_specifies_relations(docs_files, all_paths)
            if spec_rels:
                conn = cache._connect()
                # Remove old specifies relations to avoid duplicates
                conn.execute(
                    "DELETE FROM relations WHERE relation_type = ?",
                    ("specifies",),
                )
                conn.executemany(
                    "INSERT INTO relations "
                    "(src_type, src_ref, dst_type, dst_ref, relation_type, "
                    "confidence, provenance, origin_file) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            r.src_type,
                            r.src_ref,
                            r.dst_type,
                            r.dst_ref,
                            r.relation_type.value,
                            r.confidence,
                            r.provenance,
                            r.src_ref,
                        )
                        for r in spec_rels
                    ],
                )
                conn.commit()

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

        # Wiki dirty tracking (best-effort, never blocks scan)
        _wiki_dirty_count = 0
        try:
            from libs.wiki.state import ensure_wiki_table, update_dirty_state  # noqa: PLC0415

            wiki_conn = cache._connect()
            ensure_wiki_table(wiki_conn)
            _wiki_dirty_count = update_dirty_state(wiki_conn, files_processed)
            wiki_conn.commit()
        except Exception as exc:
            log.debug("wiki_dirty_tracking_failed", exc_info=exc)  # Best-effort: wiki tracking must never kill a scan

        # Embedding: upsert changed files to Qdrant (best-effort, never blocks scan)
        if changed_for_embed and only is None:
            try:
                from libs.core.projects_config import load_config  # noqa: PLC0415
                from libs.embeddings.service import embed_project_files  # noqa: PLC0415

                cfg = load_config(Path.home() / ".lvdcp" / "config.yaml")
                if cfg.qdrant.enabled:
                    embed_project_files(
                        config=cfg,
                        project_root=root,
                        project_slug=root.name,
                        changed_files=changed_for_embed,
                    )
            except Exception as exc:
                log.debug("embedding_upsert_failed", exc_info=exc)  # Best-effort: embedding must never kill a scan

        elapsed = time.perf_counter() - start
        result = ScanResult(
            files_scanned=len(files_processed),
            files_reparsed=files_reparsed,
            stale_files_removed=stale_files_removed,
            symbols_extracted=total_symbols,
            relations_reparsed=total_relations,
            relations_cached=total_relations_cached,
            elapsed_seconds=elapsed,
            wiki_dirty_count=_wiki_dirty_count,
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
