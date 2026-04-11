"""Adapter: glues the eval harness to the real retrieval pipeline.

For each eval run, builds a transient in-memory index against the fixture
repo. Cached at module level keyed by repo path — the same fixture is used
across all 20 queries in a single eval run, so we build once per run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from libs.core.entities import File
from libs.core.hashing import content_hash
from libs.core.paths import is_ignored, normalize_path
from libs.parsers.registry import detect_language, get_parser
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.retrieval.pipeline import RetrievalPipeline
from libs.storage.sqlite_cache import SqliteCache

_cached: tuple[Path, RetrievalPipeline, SqliteCache] | None = None


def _build_pipeline_for(repo: Path) -> RetrievalPipeline:
    global _cached
    if _cached is not None and _cached[0] == repo:
        return _cached[1]

    tmp = Path(tempfile.mkdtemp(prefix="lv-dcp-eval-"))
    cache = SqliteCache(tmp / "cache.db")
    cache.migrate()
    fts = FtsIndex(tmp / "fts.db")
    fts.create()
    sym_idx = SymbolIndex()

    for abs_path in repo.rglob("*"):
        if not abs_path.is_file():
            continue
        try:
            rel = normalize_path(abs_path, root=repo)
        except ValueError:
            continue
        if is_ignored(rel):
            continue
        language = detect_language(rel)
        if language == "unknown":
            continue
        parser = get_parser(language)
        if parser is None:
            continue
        try:
            data = abs_path.read_bytes()
        except OSError:
            continue
        parse_result = parser.parse(file_path=rel, data=data)

        cache.put_file(
            File(
                path=rel,
                content_hash=content_hash(data),
                size_bytes=len(data),
                language=language,
                role=parse_result.role,
            )
        )
        cache.replace_symbols(file_path=rel, symbols=parse_result.symbols)
        cache.replace_relations(file_path=rel, relations=parse_result.relations)

        try:
            text = data.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            text = ""
        # Index both file path and content so path-like queries work
        fts.index_file(rel, f"{rel}\n{text}")
        sym_idx.extend(list(parse_result.symbols))

    pipeline = RetrievalPipeline(cache=cache, fts=fts, symbols=sym_idx)
    _cached = (repo, pipeline, cache)
    return pipeline


def retrieve_for_eval(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    pipeline = _build_pipeline_for(repo)
    result = pipeline.retrieve(query, mode=mode, limit=10)
    return result.files, result.symbols
