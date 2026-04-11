"""Sanity: impact queries load, have the right shape, and refer to real fixture files."""

from tests.eval.run_eval import FIXTURE_REPO, load_impact_queries


def test_impact_queries_exist() -> None:
    queries = load_impact_queries()
    assert len(queries) == 12
    for q in queries:
        assert q["mode"] == "edit"
        assert "expected" in q
        assert "files" in q["expected"]


def test_impact_query_files_exist_in_fixture() -> None:
    queries = load_impact_queries()
    for q in queries:
        for rel_path in q["expected"]["files"]:
            abs_path = FIXTURE_REPO / rel_path
            assert abs_path.exists(), (
                f"impact query {q['id']} expects {rel_path} but it does not exist in fixture"
            )
