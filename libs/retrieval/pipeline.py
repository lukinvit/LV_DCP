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
from typing import TYPE_CHECKING

from libs.core.entities import Symbol
from libs.retrieval.fts import FtsIndex
from libs.retrieval.index import SymbolIndex
from libs.storage.sqlite_cache import SqliteCache

if TYPE_CHECKING:
    from libs.graph.builder import Graph

SYMBOL_WEIGHT = 3.0
FTS_WEIGHT = 1.0

# Files scoring below this fraction of the top file score are excluded from
# results. This improves precision for single-file queries (noise files with
# much lower scores are dropped) while keeping closely-ranked alternatives for
# multi-file queries. Tuned for Phase 1 thresholds (precision@3 ≥ 0.55).
SCORE_DECAY_THRESHOLD = 0.4


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
        graph: Graph | None = None,  # NEW Phase 2 — wired up in Task 2.5
    ) -> None:
        self._cache = cache
        self._fts = fts
        self._symbols = symbols
        self._graph = graph

    def retrieve(
        self,
        query: str,
        *,
        mode: str = "navigate",
        limit: int = 10,
    ) -> RetrievalResult:
        file_scores: dict[str, float] = defaultdict(float)
        symbol_hits: list[Symbol] = []

        # Stage 1: symbol match — use per-file best symbol score, not cumulative.
        # Accumulating all symbol hits per file inflates scores for files with
        # many symbols when the query contains generic tokens (e.g. "app" matching
        # every symbol's fq_name prefix). Instead, track the best individual
        # symbol score per file and contribute SYMBOL_WEIGHT once.
        best_sym_score: dict[str, float] = {}
        for sym, score in self._symbols.lookup(query, limit=limit * 2):
            symbol_hits.append(sym)
            if score > best_sym_score.get(sym.file_path, 0.0):
                best_sym_score[sym.file_path] = score
        for file_path, sym_score in best_sym_score.items():
            file_scores[file_path] += SYMBOL_WEIGHT * sym_score

        # Stage 2: FTS
        for path, score in self._fts.search(query, limit=limit * 2):
            file_scores[path] += FTS_WEIGHT * score

        # Rank files, applying a relative score decay cutoff to suppress noise.
        # Files scoring below SCORE_DECAY_THRESHOLD * max_score are dropped so
        # that single-file queries return a tight, high-precision list.
        ordered_files = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if ordered_files:
            max_score = ordered_files[0][1]
            cutoff = max_score * SCORE_DECAY_THRESHOLD
            ordered_files = [(p, s) for p, s in ordered_files if s >= cutoff]
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
