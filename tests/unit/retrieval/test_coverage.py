from libs.retrieval.coverage import compute_coverage


def test_coverage_high_clear_winner() -> None:
    scores = {"a": 20.0, "b": 8.0, "c": 3.0, "d": 1.0}
    assert compute_coverage(scores) == "high"


def test_coverage_medium_some_tail() -> None:
    scores = {"a": 10.0, "b": 8.0, "c": 7.0, "d": 6.5, "e": 6.0}
    assert compute_coverage(scores) == "medium"


def test_coverage_ambiguous_flat() -> None:
    scores = {"a": 10.0, "b": 9.5, "c": 9.0, "d": 8.8, "e": 8.5, "f": 8.3}
    assert compute_coverage(scores) == "ambiguous"


def test_coverage_empty_returns_ambiguous() -> None:
    assert compute_coverage({}) == "ambiguous"


def test_coverage_single_result_is_high() -> None:
    assert compute_coverage({"a": 5.0}) == "high"
