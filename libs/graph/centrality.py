"""PageRank-style centrality over the symbol/file relation graph.

Why: Aider's repo-map demonstrates that a small PageRank over a tree-sitter
symbol reference graph produces surprisingly good ranking — files/symbols with
many inbound references (widely imported, called, or inherited) rise to the
top. LV_DCP's graph layer previously exposed only adjacency and BFS, leaving
centrality implicit. Adding it as a pure function lets retrieval blend
structural importance into its scoring without disturbing the pipeline.

This module is deterministic, stdlib-only, and makes no assumptions about
node semantics (files vs symbols vs mixed) — callers pass in a `Graph` and
get back a `{node: score}` mapping where scores sum to 1.0.

Edge semantics:
    src -> dst means "src references dst" (imports, calls, inherits, ...).
    PageRank mass therefore flows from references to definitions, so a
    widely-referenced definition receives a high score.

Dangling node handling:
    Nodes with no outbound edges redistribute their mass uniformly across
    all nodes each iteration, preserving sum-to-1.
"""

from __future__ import annotations

from libs.graph.builder import Graph

DEFAULT_DAMPING = 0.85
DEFAULT_ITERATIONS = 100
DEFAULT_TOLERANCE = 1e-8


def pagerank(
    graph: Graph,
    *,
    damping: float = DEFAULT_DAMPING,
    iterations: int = DEFAULT_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute PageRank scores for every node in *graph*.

    Returns a dict {node: score} with scores in [0, 1] summing to 1.0.
    Empty graph returns {}.

    If *personalization* is given, the teleport vector is biased toward the
    specified nodes in proportion to their weights. Absent keys teleport
    nowhere; this approximates Aider's "files the user is working on"
    personalization used in its repo-map PageRank.
    """
    nodes = _collect_nodes(graph)
    if not nodes:
        return {}

    n = len(nodes)
    # Sort for determinism — Python dict iteration order is insertion-based,
    # but defaultdict from Graph may reflect relation add order, which is
    # process-dependent. Lexicographic ordering pins the power iteration.
    ordered = sorted(nodes)

    out_degree: dict[str, int] = {node: len(graph.neighbors(node)) for node in ordered}

    # Teleport vector — uniform by default, or biased by personalization.
    if personalization:
        total_weight = sum(max(0.0, personalization.get(node, 0.0)) for node in ordered)
    else:
        total_weight = 0.0
    if personalization and total_weight > 0.0:
        teleport_vec = {
            node: max(0.0, personalization.get(node, 0.0)) / total_weight for node in ordered
        }
    else:
        uniform = 1.0 / n
        teleport_vec = dict.fromkeys(ordered, uniform)

    initial = 1.0 / n
    scores: dict[str, float] = dict.fromkeys(ordered, initial)

    for _ in range(iterations):
        # Dangling mass — nodes with zero outbound edges redistribute via the
        # teleport vector (so personalization dampens dangling mass too).
        dangling_sum = sum(scores[node] for node in ordered if out_degree[node] == 0)

        new_scores: dict[str, float] = dict.fromkeys(ordered, 0.0)
        for node in ordered:
            out = out_degree[node]
            if out == 0:
                continue
            share = damping * scores[node] / out
            for nxt in graph.neighbors(node):
                new_scores[nxt] = new_scores.get(nxt, 0.0) + share

        delta = 0.0
        for node in ordered:
            val = (
                (1.0 - damping) * teleport_vec[node]
                + damping * dangling_sum * teleport_vec[node]
                + new_scores[node]
            )
            delta += abs(val - scores[node])
            new_scores[node] = val
        scores = new_scores

        if delta < tolerance:
            break

    # Renormalize to correct for float drift.
    total = sum(scores.values())
    if total > 0.0:
        scores = {k: v / total for k, v in scores.items()}
    return scores


def _collect_nodes(graph: Graph) -> set[str]:
    return graph.nodes()
