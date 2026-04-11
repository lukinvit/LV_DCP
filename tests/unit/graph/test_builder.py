from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph


def _rel(src: str, dst: str, rt: RelationType = RelationType.IMPORTS) -> Relation:
    return Relation(
        src_type="file",
        src_ref=src,
        dst_type="file",
        dst_ref=dst,
        relation_type=rt,
    )


def test_graph_neighbors() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("a.py", "c.py"))
    assert set(g.neighbors("a.py")) == {"b.py", "c.py"}


def test_graph_reverse_neighbors() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("c.py", "b.py"))
    assert set(g.reverse_neighbors("b.py")) == {"a.py", "c.py"}


def test_graph_expand_bfs() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("b.py", "c.py"))
    g.add_relation(_rel("c.py", "d.py"))
    # depth 2 from a → a, b, c
    assert g.expand("a.py", depth=2) == {"a.py", "b.py", "c.py"}


def test_graph_expand_respects_direction() -> None:
    g = Graph()
    g.add_relation(_rel("a.py", "b.py"))
    g.add_relation(_rel("b.py", "c.py"))
    # reverse expansion from c depth 2 → c, b, a
    assert g.expand("c.py", depth=2, reverse=True) == {"c.py", "b.py", "a.py"}


def test_has_node_returns_true_for_src_node() -> None:
    g = Graph()
    g.add_relation(
        Relation(
            src_type="file",
            src_ref="a.py",
            dst_type="file",
            dst_ref="b.py",
            relation_type=RelationType.IMPORTS,
        )
    )
    assert g.has_node("a.py") is True


def test_has_node_returns_true_for_dst_node() -> None:
    g = Graph()
    g.add_relation(
        Relation(
            src_type="file",
            src_ref="a.py",
            dst_type="file",
            dst_ref="b.py",
            relation_type=RelationType.IMPORTS,
        )
    )
    assert g.has_node("b.py") is True


def test_has_node_returns_false_for_unknown() -> None:
    g = Graph()
    assert g.has_node("nowhere.py") is False
