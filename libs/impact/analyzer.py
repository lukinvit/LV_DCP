"""Static impact analyzer — per-file dependency analysis via graph BFS."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph


@dataclass(frozen=True)
class ImpactReport:
    target: str
    direct_dependents: list[str] = field(default_factory=list)
    transitive_dependents: list[str] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    risk_score: float = 0.0


def _build_file_dep_map(relations: Iterable[Relation]) -> dict[str, set[str]]:
    """Build directional file dependency map from relations.

    Returns: definer_file -> set of files that import its symbols.

    Logic:
    - DEFINES relations: file -> symbol (file is the provider)
    - IMPORTS relations: file -> symbol (file is the consumer)
    - If file_a DEFINES sym and file_b IMPORTS sym, file_b depends on file_a.
      So file_a's dependents include file_b.
    """
    # symbol -> file that defines it
    symbol_to_definer: dict[str, str] = {}
    # symbol -> files that import it
    symbol_to_importers: dict[str, set[str]] = defaultdict(set)

    for rel in relations:
        if rel.relation_type == RelationType.DEFINES and rel.src_type == "file":
            symbol_to_definer[rel.dst_ref] = rel.src_ref
        elif rel.relation_type == RelationType.IMPORTS and rel.src_type == "file":
            symbol_to_importers[rel.dst_ref].add(rel.src_ref)

    # Build: file -> set of files that depend on it
    dependents_map: dict[str, set[str]] = defaultdict(set)
    for sym, definer in symbol_to_definer.items():
        for importer in symbol_to_importers.get(sym, set()):
            if importer != definer:
                dependents_map[definer].add(importer)

    return dependents_map


def _build_imports_map(relations: Iterable[Relation]) -> dict[str, set[str]]:
    """Build: file -> set of files it imports from (depends on)."""
    symbol_to_definer: dict[str, str] = {}
    file_imports_symbols: dict[str, set[str]] = defaultdict(set)

    for rel in relations:
        if rel.relation_type == RelationType.DEFINES and rel.src_type == "file":
            symbol_to_definer[rel.dst_ref] = rel.src_ref
        elif rel.relation_type == RelationType.IMPORTS and rel.src_type == "file":
            file_imports_symbols[rel.src_ref].add(rel.dst_ref)

    imports_map: dict[str, set[str]] = defaultdict(set)
    for file, syms in file_imports_symbols.items():
        for sym in syms:
            definer = symbol_to_definer.get(sym)
            if definer and definer != file:
                imports_map[file].add(definer)

    return imports_map


def analyze_impact(  # noqa: PLR0913
    target: str,
    graph: Graph,
    *,
    relations: Iterable[Relation] | None = None,
    file_roles: dict[str, str] | None = None,
    max_depth: int = 4,
    git_churn: int = 0,
) -> ImpactReport:
    """Analyze impact of changing *target* file.

    Uses typed relations to build a directional file-level dependency map,
    then performs BFS for transitive dependents up to *max_depth*.

    Parameters
    ----------
    target:
        File path to analyze.
    graph:
        The project graph (used for fan metrics).
    relations:
        Typed Relation objects. If None, falls back to graph-only heuristic
        (symmetric, less accurate).
    file_roles:
        Mapping of file path -> role ("test", "source", etc.).
    max_depth:
        Maximum BFS depth for transitive dependents.
    git_churn:
        Number of recent commits touching this file (amplifies risk).
    """
    roles = file_roles or {}

    # Build directional maps from relations
    if relations is not None:
        rel_list = list(relations)
        dep_map = _build_file_dep_map(rel_list)
        imports_map = _build_imports_map(rel_list)
    else:
        dep_map = {}
        imports_map = {}

    # Direct dependents: files that import symbols defined by target
    direct = sorted(dep_map.get(target, set()))

    # BFS for transitive dependents
    visited: set[str] = {target}
    visited.update(direct)
    transitive: list[str] = []

    if max_depth > 1:
        frontier: deque[tuple[str, int]] = deque([(d, 1) for d in direct])
        while frontier:
            node, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            for nxt in dep_map.get(node, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    transitive.append(nxt)
                    frontier.append((nxt, depth + 1))

    transitive.sort()

    # Affected tests: test files among all dependents
    all_dependents = set(direct) | set(transitive)
    affected_tests = sorted(
        f for f in all_dependents if roles.get(f) == "test" or "/test" in f or f.startswith("test")
    )

    # Risk score: fan_in * max(1, fan_out) * (1 + git_churn / 10)
    fan_in = len(direct)
    fan_out = len(imports_map.get(target, set()))
    risk = fan_in * max(1, fan_out) * (1.0 + git_churn / 10.0)

    return ImpactReport(
        target=target,
        direct_dependents=direct,
        transitive_dependents=transitive,
        affected_tests=affected_tests,
        risk_score=risk,
    )
