"""Multi-stage deterministic retrieval.

Phase 1 stages:
1. Symbol exact / substring match → candidate symbols, their files
2. FTS5 full-text search → candidate files by content
3. Merge with weighted scoring, stable tie-breaking
4. Return files and symbols ordered by combined score

Phase 2 adds: vector stage, rerank. Wire points preserved in TODO comments.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from libs.core.entities import Symbol
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.storage.sqlite_cache import SqliteCache

SYMBOL_WEIGHT = 3.0
FTS_WEIGHT = 1.0


@dataclass(frozen=True)
class RetrievalResult:
    files: list[str]
    symbols: list[str]
    scores: dict[str, float]


class RetrievalPipeline:
    def __init__(
        self,
        *,
        cache: SqliteCache,
        fts: FtsIndex,
        symbols: SymbolIndex,
    ) -> None:
        self._cache = cache
        self._fts = fts
        self._symbols = symbols

    def retrieve(
        self,
        query: str,
        *,
        mode: str = "navigate",
        limit: int = 10,
    ) -> RetrievalResult:
        file_scores: dict[str, float] = defaultdict(float)
        symbol_hits: list[Symbol] = []

        # Stage 1: symbol match
        for sym in self._symbols.lookup(query, limit=limit * 2):
            symbol_hits.append(sym)
            file_scores[sym.file_path] += SYMBOL_WEIGHT

        # Stage 2: FTS
        for path, score in self._fts.search(query, limit=limit * 2):
            file_scores[path] += FTS_WEIGHT * score

        # Rank files
        ordered_files = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        files = [p for p, _ in ordered_files[:limit]]

        # Deduplicate symbols by fq_name, keep insertion order
        seen: set[str] = set()
        symbol_fqs: list[str] = []
        for sym in symbol_hits:
            if sym.fq_name not in seen:
                seen.add(sym.fq_name)
                symbol_fqs.append(sym.fq_name)
        symbol_fqs = symbol_fqs[:limit]

        return RetrievalResult(
            files=files,
            symbols=symbol_fqs,
            scores=dict(file_scores),
        )
