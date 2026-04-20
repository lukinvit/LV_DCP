"""Simple directed graph with BFS expansion and cached centrality."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from libs.core.entities import Relation


class Graph:
    def __init__(self) -> None:
        self._fwd: dict[str, set[str]] = defaultdict(set)
        self._rev: dict[str, set[str]] = defaultdict(set)
        self._relation_count = 0
        self._pagerank_cache: dict[str, float] | None = None

    def add_relation(self, rel: Relation) -> None:
        self._fwd[rel.src_ref].add(rel.dst_ref)
        self._rev[rel.dst_ref].add(rel.src_ref)
        self._relation_count += 1
        self._pagerank_cache = None

    def add_relations(self, rels: Iterable[Relation]) -> None:
        for r in rels:
            self.add_relation(r)

    def neighbors(self, node: str) -> set[str]:
        return set(self._fwd.get(node, set()))

    def reverse_neighbors(self, node: str) -> set[str]:
        return set(self._rev.get(node, set()))

    def has_node(self, name: str) -> bool:
        """Return True if *name* appears as either a source or destination in any relation."""
        return name in self._fwd or name in self._rev

    def nodes(self) -> set[str]:
        """Return every node that appears as a source or destination."""
        result: set[str] = set()
        for src, dsts in self._fwd.items():
            result.add(src)
            result.update(dsts)
        result.update(self._rev.keys())
        return result

    def expand(self, seed: str, *, depth: int, reverse: bool = False) -> set[str]:
        adj = self._rev if reverse else self._fwd
        visited: set[str] = {seed}
        frontier: deque[tuple[str, int]] = deque([(seed, 0)])
        while frontier:
            node, d = frontier.popleft()
            if d >= depth:
                continue
            for nxt in adj.get(node, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    frontier.append((nxt, d + 1))
        return visited

    def relation_count(self) -> int:
        return self._relation_count

    def pagerank(self) -> dict[str, float]:
        """Return PageRank scores, cached until the next `add_relation`.

        The cache keeps repeated retrieval calls cheap — centrality only needs
        to recompute when the graph structure changes. The ``pagerank`` helper
        is imported lazily to avoid a module-level circular import (the
        centrality module takes a ``Graph`` as its first argument).
        """
        if self._pagerank_cache is None:
            from libs.graph.centrality import pagerank  # noqa: PLC0415

            self._pagerank_cache = pagerank(self)
        return self._pagerank_cache
