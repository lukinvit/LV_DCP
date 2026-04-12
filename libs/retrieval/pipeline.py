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
GRAPH_EXPANSION_DEPTH_EDIT = 3
GRAPH_EXPANSION_DECAY = 0.7
GRAPH_SEED_COUNT = 5  # how many top candidates seed graph expansion

ROLE_WEIGHTS_NAVIGATE: dict[str, float] = {
    "source": 1.0,
    "test": 0.85,
    "config": 1.10,
    "docs": 0.35,
    "other": 0.70,
}
ROLE_WEIGHTS_EDIT: dict[str, float] = {
    "source": 1.0,
    "test": 0.95,
    "config": 1.15,
    "docs": 0.40,
    "other": 0.70,
}
DOCS_OVERRIDE_KEYWORDS: frozenset[str] = frozenset(
    {
        "docs",
        "documentation",
        "readme",
        "changelog",
        "architecture",
        "design",
        "spec",
        "adr",
    }
)
DOCS_OVERRIDE_MULTIPLIER = 1.20

CONFIG_TRIGGER_KEYWORDS: frozenset[str] = frozenset(
    {
        "config",
        "settings",
        "timeout",
        "ttl",
        "schedule",
        "lifetime",
        "env",
        "port",
        "url",
        "host",
        "secret",
        "credential",
        "database",
        "db",
        "connection",
    }
)
CONFIG_BOOST_FRACTION = 0.5
CONFIG_BOOST_FLOOR = 0.5

GIT_CHURN_BOOST = 1.10
GIT_NEW_FILE_BOOST = 1.05


def _apply_git_boost(
    file_scores: dict[str, float],
    git_stats: dict[str, object],
) -> None:
    """Boost recently active files in ranking. Mutates file_scores."""
    for path in list(file_scores):
        stats = git_stats.get(path)
        if stats is None:
            continue
        if stats.churn_30d > 0:  # type: ignore[union-attr]
            file_scores[path] *= GIT_CHURN_BOOST
        if stats.age_days < 30:  # type: ignore[union-attr]
            file_scores[path] *= GIT_NEW_FILE_BOOST


def _maybe_boost_config_files(
    query: str,
    file_scores: dict[str, float],
    file_roles: dict[str, str],
) -> None:
    """Inject config files into candidate pool when query mentions config terms."""
    query_words = set(query.lower().split())
    if not query_words & CONFIG_TRIGGER_KEYWORDS:
        return
    baseline = (
        max(file_scores.values()) * CONFIG_BOOST_FRACTION if file_scores else CONFIG_BOOST_FLOOR
    )
    for path, role in file_roles.items():
        if role == "config":
            current = file_scores.get(path, 0.0)
            file_scores[path] = max(current, baseline)


def _apply_role_weights(
    file_scores: dict[str, float],
    file_roles: dict[str, str],
    query: str,
    mode: str,
) -> None:
    """Multiply each candidate's score by its role weight. Mutates file_scores."""
    weights = ROLE_WEIGHTS_EDIT if mode == "edit" else ROLE_WEIGHTS_NAVIGATE
    query_lower = query.lower()
    wants_docs = any(kw in query_lower for kw in DOCS_OVERRIDE_KEYWORDS)
    for path in list(file_scores):
        score = file_scores[path]
        role = file_roles.get(path, "other")
        if wants_docs and role == "docs":
            file_scores[path] = score * DOCS_OVERRIDE_MULTIPLIER
        else:
            file_scores[path] = score * weights.get(role, 0.70)


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
        self._file_roles: dict[str, str] | None = None
        self._git_stats: dict[str, object] | None = None

    def _get_git_stats(self) -> dict[str, object]:
        if self._git_stats is None:
            self._git_stats = {s.file_path: s for s in self._cache.iter_git_stats()}
        return self._git_stats

    def _get_file_roles(self) -> dict[str, str]:
        if self._file_roles is None:
            self._file_roles = {f.path: f.role for f in self._cache.iter_files()}
        return self._file_roles

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
        stages.append(
            self._stage_symbol(query, limit, file_scores, symbol_hits, initial_candidates)
        )

        # Stage 2: FTS
        stages.append(self._stage_fts(query, limit, file_scores, initial_candidates))

        # Stage 3: graph expansion (Phase 2)
        expanded_candidates: list[Candidate] = []
        if self._graph is not None and file_scores:
            stage, expanded_candidates = self._stage_graph(self._graph, file_scores, mode)
            stages.append(stage)

        # Config file boost (D2) — before role weights so config boost gets multiplied
        roles = self._get_file_roles()
        _maybe_boost_config_files(query, file_scores, roles)

        # Role-weighted score fusion (D1)
        _apply_role_weights(file_scores, roles, query, mode)

        # Git intelligence boost
        git_stats = self._get_git_stats()
        if git_stats:
            _apply_git_boost(file_scores, git_stats)

        # Stage 4: score decay cutoff + final rank
        ordered, dropped = _apply_score_decay(file_scores)

        final_files = [p for p, _ in ordered[:limit]]
        final_scores = dict(ordered[:limit])

        symbol_fqs = self._build_symbol_list(symbol_hits, final_files, limit)

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

    # ------------------------------------------------------------------
    # Private stage helpers
    # ------------------------------------------------------------------

    def _stage_symbol(
        self,
        query: str,
        limit: int,
        file_scores: dict[str, float],
        symbol_hits: list[Symbol],
        initial_candidates: list[Candidate],
    ) -> StageResult:
        t0 = time.perf_counter()
        symbol_results = self._symbols.lookup(query, limit=limit * 2)
        for sym, score in symbol_results:
            symbol_hits.append(sym)
            boosted = SYMBOL_WEIGHT * score
            file_scores[sym.file_path] = max(file_scores[sym.file_path], boosted)
            initial_candidates.append(Candidate(path=sym.file_path, score=boosted, source="symbol"))
        return StageResult(
            name="symbol_match",
            candidate_count=len(symbol_results),
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    def _stage_fts(
        self,
        query: str,
        limit: int,
        file_scores: dict[str, float],
        initial_candidates: list[Candidate],
    ) -> StageResult:
        t0 = time.perf_counter()
        fts_results = self._fts.search(query, limit=limit * 2)
        for path, score in fts_results:
            file_scores[path] += FTS_WEIGHT * score
            initial_candidates.append(Candidate(path=path, score=FTS_WEIGHT * score, source="fts"))
        return StageResult(
            name="fts",
            candidate_count=len(fts_results),
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    def _stage_graph(
        self,
        graph: Graph,
        file_scores: dict[str, float],
        mode: str,
    ) -> tuple[StageResult, list[Candidate]]:
        t0 = time.perf_counter()
        top_seeds = dict(sorted(file_scores.items(), key=lambda kv: -kv[1])[:GRAPH_SEED_COUNT])
        expansion_weight = 1.0 if mode == "edit" else 0.5
        expanded_candidates: list[Candidate] = []
        depth = GRAPH_EXPANSION_DEPTH_EDIT if mode == "edit" else GRAPH_EXPANSION_DEPTH
        for expanded in expand_via_graph(
            top_seeds,
            graph,
            depth=depth,
            decay=GRAPH_EXPANSION_DECAY,
        ):
            boosted_score = expanded.score * expansion_weight
            file_scores[expanded.path] = max(file_scores.get(expanded.path, 0.0), boosted_score)
            expanded_candidates.append(
                Candidate(path=expanded.path, score=boosted_score, source=f"graph_{expanded.via}")
            )
        stage = StageResult(
            name="graph_expansion",
            candidate_count=len(expanded_candidates),
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
        return stage, expanded_candidates

    def _build_symbol_list(
        self,
        symbol_hits: list[Symbol],
        final_files: list[str],
        limit: int,
    ) -> list[str]:
        """Build ordered, deduplicated symbol FQ-name list.

        Starts with symbols from Stage-1 direct matching, then supplements
        with all symbols from top-ranked files that produced no Stage-1 hits.
        This ensures graph-expanded files also contribute their key symbols.
        """
        seen: set[str] = set()
        symbol_fqs: list[str] = []
        for sym in symbol_hits:
            if sym.fq_name not in seen:
                seen.add(sym.fq_name)
                symbol_fqs.append(sym.fq_name)

        files_with_direct_symbols: set[str] = {sym.file_path for sym in symbol_hits}
        supplement_files = set(f for f in final_files[:2] if f not in files_with_direct_symbols)
        for sym in self._symbols._symbols:
            if sym.fq_name in seen or "#" in sym.fq_name:
                continue
            if sym.file_path in supplement_files:
                seen.add(sym.fq_name)
                symbol_fqs.append(sym.fq_name)

        return symbol_fqs[:limit]


def _apply_score_decay(
    file_scores: dict[str, float],
) -> tuple[list[tuple[str, float]], list[Candidate]]:
    """Sort by score, drop entries below SCORE_DECAY_THRESHOLD x top score."""
    ordered = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    dropped: list[Candidate] = []
    if not ordered:
        return ordered, dropped
    floor = ordered[0][1] * SCORE_DECAY_THRESHOLD
    kept: list[tuple[str, float]] = []
    for p, s in ordered:
        if s >= floor:
            kept.append((p, s))
        else:
            dropped.append(Candidate(path=p, score=s, source="decayed"))
    return kept, dropped


def rrf_fuse(
    rankings: list[dict[str, float]],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion across multiple score dictionaries.

    Each ranking is a dict of {file_path: score}. Results are fused by
    summing 1/(k + rank + 1) for each ranking. Higher k smooths differences.
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        sorted_items = sorted(ranking.items(), key=lambda x: -x[1])
        for rank, (key, _) in enumerate(sorted_items):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
    return fused
