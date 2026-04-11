"""Graph expansion stage for the retrieval pipeline.

Takes a set of seed files (from the keyword match / FTS stages) and walks
the relation graph up to `depth` hops, producing additional candidates
with decayed scores.

Forward walk: what does this file use (imports, calls).
Reverse walk: what uses this file (reverse imports) — finds tests/callers.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from libs.graph.builder import Graph


@dataclass(frozen=True)
class ExpandedCandidate:
    path: str
    score: float
    hop_distance: int
    via: str  # "forward" | "reverse" | "both"


@dataclass
class _WalkContext:
    graph: Graph
    seeds_set: set[str]
    depth: int
    decay: float
    results: dict[str, tuple[float, int, str]]


def expand_via_graph(
    seeds: dict[str, float],
    graph: Graph,
    *,
    depth: int,
    decay: float,
) -> list[ExpandedCandidate]:
    """BFS expansion from seeds in both directions, with score decay."""
    # path -> (best_score, best_hop, via)
    results: dict[str, tuple[float, int, str]] = {}
    ctx = _WalkContext(
        graph=graph,
        seeds_set=set(seeds.keys()),
        depth=depth,
        decay=decay,
        results=results,
    )

    for seed_path, seed_score in seeds.items():
        _walk(ctx, seed_path=seed_path, seed_score=seed_score, reverse=False, direction="forward")
        _walk(ctx, seed_path=seed_path, seed_score=seed_score, reverse=True, direction="reverse")

    return [
        ExpandedCandidate(path=path, score=score, hop_distance=hop, via=via)
        for path, (score, hop, via) in results.items()
    ]


def _walk(
    ctx: _WalkContext,
    *,
    seed_path: str,
    seed_score: float,
    reverse: bool,
    direction: str,
) -> None:
    visited: set[str] = {seed_path}
    queue: deque[tuple[str, int]] = deque([(seed_path, 0)])
    while queue:
        node, hop = queue.popleft()
        if hop >= ctx.depth:
            continue
        neighbors = ctx.graph.reverse_neighbors(node) if reverse else ctx.graph.neighbors(node)
        for nxt in neighbors:
            if nxt in visited:
                continue
            visited.add(nxt)
            if nxt in ctx.seeds_set:
                continue  # don't expand into other seeds
            new_hop = hop + 1
            decayed_score = seed_score * (ctx.decay**new_hop)
            prev = ctx.results.get(nxt)
            if prev is None or decayed_score > prev[0]:
                via = direction if prev is None else ("both" if prev[2] != direction else direction)
                ctx.results[nxt] = (decayed_score, new_hop, via)
            queue.append((nxt, new_hop))
