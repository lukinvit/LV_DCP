"""Multi-stage deterministic retrieval pipeline with graph expansion.

Stages:
1. Symbol exact / substring match
2. FTS5 full-text search
3. Merge with weighted scoring
4. Graph expansion (Phase 2 — adds impacted files reachable via graph)
5. Final rank with score decay cutoff
6. Build RetrievalTrace for explainability
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass

from libs.core.entities import Symbol
from libs.graph.builder import Graph
from libs.retrieval.coverage import Coverage, compute_coverage
from libs.retrieval.fts import FtsIndex
from libs.retrieval.graph_expansion import expand_via_graph
from libs.retrieval.index import SymbolIndex
from libs.retrieval.trace import Candidate, RetrievalTrace, StageResult
from libs.storage.sqlite_cache import SqliteCache

SYMBOL_WEIGHT = 3.0
FTS_WEIGHT = 1.0
SCORE_DECAY_THRESHOLD = 0.4
GRAPH_EXPANSION_DEPTH = 2
GRAPH_EXPANSION_DECAY = 0.5
GRAPH_SEED_COUNT = 5  # how many top candidates seed graph expansion


@dataclass(frozen=True)
class RetrievalResult:
    files: list[str]
    symbols: list[str]
    scores: dict[str, float]
    trace: RetrievalTrace
    coverage: Coverage


class RetrievalPipeline:
    def __init__(
        self,
        *,
        cache: SqliteCache,
        fts: FtsIndex,
        symbols: SymbolIndex,
        graph: Graph | None = None,
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
        stages: list[StageResult] = []
        file_scores: dict[str, float] = defaultdict(float)
        symbol_hits: list[Symbol] = []
        initial_candidates: list[Candidate] = []

        # Stage 1: symbol match
        t0 = time.perf_counter()
        symbol_results = self._symbols.lookup(query, limit=limit * 2)
        for sym, score in symbol_results:
            symbol_hits.append(sym)
            file_scores[sym.file_path] = max(file_scores[sym.file_path], SYMBOL_WEIGHT * score)
            initial_candidates.append(
                Candidate(path=sym.file_path, score=SYMBOL_WEIGHT * score, source="symbol")
            )
        stages.append(
            StageResult(
                name="symbol_match",
                candidate_count=len(symbol_results),
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )
        )

        # Stage 2: FTS
        t0 = time.perf_counter()
        fts_results = self._fts.search(query, limit=limit * 2)
        for path, score in fts_results:
            file_scores[path] += FTS_WEIGHT * score
            initial_candidates.append(Candidate(path=path, score=FTS_WEIGHT * score, source="fts"))
        stages.append(
            StageResult(
                name="fts",
                candidate_count=len(fts_results),
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )
        )

        # Stage 3: graph expansion (Phase 2)
        expanded_candidates: list[Candidate] = []
        if self._graph is not None and file_scores:
            t0 = time.perf_counter()
            # Take top-K seeds for expansion
            top_seeds = dict(sorted(file_scores.items(), key=lambda kv: -kv[1])[:GRAPH_SEED_COUNT])
            expansion_weight = 1.0 if mode == "edit" else 0.5
            for expanded in expand_via_graph(
                top_seeds,
                self._graph,
                depth=GRAPH_EXPANSION_DEPTH,
                decay=GRAPH_EXPANSION_DECAY,
            ):
                boosted_score = expanded.score * expansion_weight
                if expanded.path not in file_scores:
                    file_scores[expanded.path] = boosted_score
                else:
                    file_scores[expanded.path] = max(file_scores[expanded.path], boosted_score)
                source = f"graph_{expanded.via}"
                expanded_candidates.append(
                    Candidate(path=expanded.path, score=boosted_score, source=source)
                )
            stages.append(
                StageResult(
                    name="graph_expansion",
                    candidate_count=len(expanded_candidates),
                    elapsed_ms=(time.perf_counter() - t0) * 1000,
                )
            )

        # Stage 4: score decay cutoff + final rank
        ordered = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        dropped: list[Candidate] = []
        if ordered:
            top_score = ordered[0][1]
            floor = top_score * SCORE_DECAY_THRESHOLD
            kept: list[tuple[str, float]] = []
            for p, s in ordered:
                if s >= floor:
                    kept.append((p, s))
                else:
                    dropped.append(Candidate(path=p, score=s, source="decayed"))
            ordered = kept

        final_files = [p for p, _ in ordered[:limit]]
        final_scores = dict(ordered[:limit])

        # Deduplicate symbols by fq_name, keep insertion order
        seen: set[str] = set()
        symbol_fqs: list[str] = []
        for sym in symbol_hits:
            if sym.fq_name not in seen:
                seen.add(sym.fq_name)
                symbol_fqs.append(sym.fq_name)
        symbol_fqs = symbol_fqs[:limit]

        coverage: Coverage = compute_coverage(final_scores)

        final_ranking = [Candidate(path=p, score=s, source="final") for p, s in ordered[:limit]]

        trace = RetrievalTrace(
            trace_id=str(uuid.uuid4()),
            project="",  # filled by ProjectIndex
            query=query,
            mode=mode,
            timestamp=time.time(),
            stages=stages,
            initial_candidates=initial_candidates,
            expanded_via_graph=expanded_candidates,
            dropped_by_score_decay=dropped,
            final_ranking=final_ranking,
            coverage=coverage,
        )

        return RetrievalResult(
            files=final_files,
            symbols=symbol_fqs,
            scores=final_scores,
            trace=trace,
            coverage=coverage,
        )
