"""Targeted tests for _walk_mixed sub-walks A (caller discovery) and B
(dependency discovery). Uses hand-built minimal graphs to assert the
expansion produces exactly the expected file nodes.
"""

from __future__ import annotations

from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph
from libs.retrieval.graph_expansion import expand_via_graph


def _rel(src: str, dst: str, rt: RelationType) -> Relation:
    return Relation(
        src_type="file",
        src_ref=src,
        dst_type="symbol",
        dst_ref=dst,
        relation_type=rt,
    )


# --------- Sub-walk A: seed owns a symbol, another file imports it ---------


def test_sub_walk_A_finds_single_caller() -> None:
    """app/services/auth.py defines authenticate;
    app/handlers/login.py imports app.services.auth.authenticate → caller discoverable."""
    g = Graph()
    g.add_relation(
        _rel("app/services/auth.py", "app.services.auth.authenticate", RelationType.DEFINES)
    )
    g.add_relation(
        _rel("app/handlers/login.py", "app.services.auth.authenticate", RelationType.IMPORTS)
    )
    seeds = {"app/services/auth.py": 10.0}

    expanded = expand_via_graph(seeds, g, depth=2, decay=0.5)
    paths = {c.path for c in expanded}

    assert "app/handlers/login.py" in paths, f"caller not found; got {paths}"


def test_sub_walk_A_multiple_callers_deduped() -> None:
    g = Graph()
    g.add_relation(
        _rel("app/services/auth.py", "app.services.auth.authenticate", RelationType.DEFINES)
    )
    g.add_relation(
        _rel("app/handlers/login.py", "app.services.auth.authenticate", RelationType.IMPORTS)
    )
    g.add_relation(
        _rel("app/handlers/register.py", "app.services.auth.authenticate", RelationType.IMPORTS)
    )
    seeds = {"app/services/auth.py": 10.0}

    expanded = expand_via_graph(seeds, g, depth=2, decay=0.5)
    paths = {c.path for c in expanded}

    assert "app/handlers/login.py" in paths
    assert "app/handlers/register.py" in paths


def test_sub_walk_A_ignores_external_symbols_owned_by_seed() -> None:
    """A symbol whose FQ name does NOT start with the seed's module prefix
    must not be treated as 'own' symbol."""
    g = Graph()
    g.add_relation(
        _rel("app/handlers/login.py", "fastapi.APIRouter", RelationType.IMPORTS)
    )
    seeds = {"app/handlers/login.py": 10.0}

    expanded = expand_via_graph(seeds, g, depth=2, decay=0.5)
    paths = {c.path for c in expanded}

    # No own-symbol edges → sub-walk A produces nothing.
    # Sub-walk B also produces nothing because fastapi.APIRouter has no defining file in the graph.
    assert paths == set()


# --------- Sub-walk B: seed imports a project symbol whose path derivable ---------


def test_sub_walk_B_finds_defining_file() -> None:
    """app/handlers/login.py imports app.services.auth.authenticate →
    sub-walk B derives app/services/auth.py as the defining file."""
    g = Graph()
    # seed imports a project-module symbol
    g.add_relation(
        _rel("app/handlers/login.py", "app.services.auth.authenticate", RelationType.IMPORTS)
    )
    # graph must have the defining file as a node for has_node() to succeed
    g.add_relation(
        _rel("app/services/auth.py", "app.services.auth.authenticate", RelationType.DEFINES)
    )
    seeds = {"app/handlers/login.py": 10.0}

    expanded = expand_via_graph(seeds, g, depth=2, decay=0.5)
    paths = {c.path for c in expanded}

    assert "app/services/auth.py" in paths, f"defining file not found; got {paths}"


def test_sub_walk_B_skips_external_libraries() -> None:
    """Symbols from external libs (fastapi.*, …) must not generate file candidates
    because the derived path is not present in the graph."""
    g = Graph()
    g.add_relation(
        _rel("app/handlers/login.py", "fastapi.APIRouter", RelationType.IMPORTS)
    )
    seeds = {"app/handlers/login.py": 10.0}

    expanded = expand_via_graph(seeds, g, depth=2, decay=0.5)
    paths = {c.path for c in expanded}

    assert "fastapi/APIRouter.py" not in paths


def test_sub_walk_B_skips_single_component_symbols() -> None:
    """`datetime` has no module prefix and cannot be mapped to a project file."""
    g = Graph()
    g.add_relation(
        _rel("app/handlers/login.py", "datetime", RelationType.IMPORTS)
    )
    seeds = {"app/handlers/login.py": 10.0}

    expanded = expand_via_graph(seeds, g, depth=2, decay=0.5)
    paths = {c.path for c in expanded}

    assert paths == set()
