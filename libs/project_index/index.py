"""Single entry point for opening a project's index.

Consolidates what Phase 1 duplicated across:
- apps/cli/commands/scan.py
- apps/cli/commands/pack.py
- apps/cli/commands/inspect.py
- tests/eval/retrieval_adapter.py

Plus the new Phase 2 consumers:
- apps/mcp/tools.py
- apps/agent/daemon.py
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Self

from libs.core.entities import File, Relation, Symbol
from libs.graph.builder import Graph
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.retrieval.pipeline import RetrievalPipeline, RetrievalResult
from libs.retrieval.trace import RetrievalTrace, load_trace, save_trace
from libs.scanning.scanner import CACHE_REL, FTS_REL
from libs.storage.sqlite_cache import SqliteCache


class ProjectNotIndexedError(RuntimeError):
    """Raised when a project has no .context/cache.db yet."""


class ProjectIndex:
    """Holds the cache, FTS, symbol index, graph, and pipeline for one project."""

    def __init__(
        self,
        root: Path,
        cache: SqliteCache,
        fts: FtsIndex,
        symbols: SymbolIndex,
        graph: Graph,
    ) -> None:
        self.root = root.resolve()
        self._cache = cache
        self._fts = fts
        self._symbols = symbols
        self._graph = graph
        self._pipeline = RetrievalPipeline(
            cache=cache,
            fts=fts,
            symbols=symbols,
            graph=graph,  # Phase 2 adds graph to pipeline signature
        )

    @classmethod
    def open(cls, root: Path) -> Self:
        """Open an existing indexed project. Raises if not indexed."""
        root = root.resolve()
        cache_path = root / CACHE_REL
        if not cache_path.exists():
            raise ProjectNotIndexedError(f"no cache at {cache_path}. Run `ctx scan {root}` first.")
        return cls._build(root)

    @classmethod
    def for_scan(cls, root: Path) -> Self:
        """Open or create. Used by scanner before any data exists."""
        return cls._build(root.resolve())

    @classmethod
    def _build(cls, root: Path) -> Self:
        cache = SqliteCache(root / CACHE_REL)
        cache.migrate()
        fts = FtsIndex(root / FTS_REL)
        fts.create()

        sym_idx = SymbolIndex()
        for sym in cache.iter_symbols():
            sym_idx.add(sym)

        graph = Graph()
        for rel in cache.iter_relations():
            graph.add_relation(rel)

        return cls(root=root, cache=cache, fts=fts, symbols=sym_idx, graph=graph)

    def retrieve(
        self,
        query: str,
        *,
        mode: str = "navigate",
        limit: int = 10,
    ) -> RetrievalResult:
        return self._pipeline.retrieve(query, mode=mode, limit=limit)

    def file_count(self) -> int:
        return self._cache.file_count()

    def delete_file(self, path: str) -> None:
        """Remove a single file from the index (used by the daemon on deletion events)."""
        self._cache.delete_file(path)
        self._fts.delete_file(path)

    # ------------------------------------------------------------------
    # Public accessors — keep callers off private _cache / _fts handles.
    # ------------------------------------------------------------------

    def iter_files(self) -> Iterator[File]:
        return self._cache.iter_files()

    def iter_symbols(self) -> Iterator[Symbol]:
        return self._cache.iter_symbols()

    def iter_relations(self) -> Iterator[Relation]:
        return self._cache.iter_relations()

    def save_trace(self, trace: RetrievalTrace) -> None:
        save_trace(self._cache, trace)

    def load_trace(self, trace_id: str) -> RetrievalTrace | None:
        return load_trace(self._cache, trace_id)

    def close(self) -> None:
        self._fts.close()
        self._cache.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
