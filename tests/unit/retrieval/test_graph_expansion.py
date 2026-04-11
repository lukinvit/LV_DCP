from libs.core.entities import Relation, RelationType
from libs.graph.builder import Graph
from libs.retrieval.graph_expansion import expand_via_graph


def _rel(src: str, dst: str, rt: RelationType = RelationType.IMPORTS) -> Relation:
    return Relation(
        src_type="file",
        src_ref=src,
        dst_type="file",
        dst_ref=dst,
        relation_type=rt,
    )


def test_expand_forward_one_hop() -> None:
    graph = Graph()
    graph.add_relation(_rel("a.py", "b.py"))
    seeds = {"a.py": 10.0}
    expanded = expand_via_graph(seeds, graph, depth=2, decay=0.5)
    by_path = {c.path: c for c in expanded}
    assert "b.py" in by_path
    assert by_path["b.py"].score == 5.0  # 10 * 0.5^1
    assert by_path["b.py"].hop_distance == 1


def test_expand_forward_two_hops_decays() -> None:
    graph = Graph()
    graph.add_relation(_rel("a.py", "b.py"))
    graph.add_relation(_rel("b.py", "c.py"))
    seeds = {"a.py": 10.0}
    expanded = expand_via_graph(seeds, graph, depth=2, decay=0.5)
    by_path = {c.path: c for c in expanded}
    assert by_path["c.py"].score == 2.5  # 10 * 0.5^2
    assert by_path["c.py"].hop_distance == 2


def test_expand_reverse_walk_included() -> None:
    graph = Graph()
    graph.add_relation(_rel("x.py", "target.py"))  # x imports target
    seeds = {"target.py": 10.0}
    expanded = expand_via_graph(seeds, graph, depth=2, decay=0.5)
    by_path = {c.path: c for c in expanded}
    # Reverse walk from target must surface x.py — this is what finds "who uses this file"
    assert "x.py" in by_path
    assert by_path["x.py"].score == 5.0


def test_expand_skips_seeds_themselves() -> None:
    graph = Graph()
    graph.add_relation(_rel("a.py", "b.py"))
    seeds = {"a.py": 10.0}
    expanded = expand_via_graph(seeds, graph, depth=2, decay=0.5)
    paths = {c.path for c in expanded}
    assert "a.py" not in paths  # seeds not included in expansion output


def test_expand_multiple_paths_dedupe_highest_score() -> None:
    graph = Graph()
    graph.add_relation(_rel("a.py", "c.py"))
    graph.add_relation(_rel("b.py", "c.py"))
    seeds = {"a.py": 10.0, "b.py": 8.0}
    expanded = expand_via_graph(seeds, graph, depth=2, decay=0.5)
    by_path = {c.path: c for c in expanded}
    # c.py reachable from both; keep the highest-decayed score
    assert by_path["c.py"].score == 5.0  # max(10*0.5, 8*0.5)
