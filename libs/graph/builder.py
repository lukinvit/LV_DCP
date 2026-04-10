"""Simple directed graph with BFS expansion."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from libs.core.entities import Relation


class Graph:
    def __init__(self) -> None:
        self._fwd: dict[str, set[str]] = defaultdict(set)
        self._rev: dict[str, set[str]] = defaultdict(set)
        self._relation_count = 0

    def add_relation(self, rel: Relation) -> None:
        self._fwd[rel.src_ref].add(rel.dst_ref)
        self._rev[rel.dst_ref].add(rel.src_ref)
        self._relation_count += 1

    def add_relations(self, rels: Iterable[Relation]) -> None:
        for r in rels:
            self.add_relation(r)

    def neighbors(self, node: str) -> set[str]:
        return set(self._fwd.get(node, set()))

    def reverse_neighbors(self, node: str) -> set[str]:
        return set(self._rev.get(node, set()))

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
