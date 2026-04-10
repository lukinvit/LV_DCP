from tests.eval.metrics import mean_reciprocal_rank, precision_at_k, recall_at_k


def test_recall_at_k_all_hit() -> None:
    retrieved = ["a.py", "b.py", "c.py"]
    expected = ["a.py", "b.py"]
    assert recall_at_k(retrieved, expected, k=3) == 1.0


def test_recall_at_k_partial() -> None:
    retrieved = ["a.py", "x.py", "y.py"]
    expected = ["a.py", "b.py"]
    assert recall_at_k(retrieved, expected, k=3) == 0.5


def test_recall_at_k_none() -> None:
    assert recall_at_k(["x.py"], ["a.py"], k=5) == 0.0


def test_recall_at_k_empty_expected_is_one() -> None:
    # Empty expected set means no ground truth to miss
    assert recall_at_k(["a.py"], [], k=3) == 1.0


def test_precision_at_k_half() -> None:
    retrieved = ["a.py", "x.py", "b.py", "y.py"]
    expected = ["a.py", "b.py"]
    assert precision_at_k(retrieved, expected, k=4) == 0.5


def test_precision_at_k_respects_k() -> None:
    retrieved = ["a.py", "b.py", "c.py"]
    expected = ["a.py", "b.py"]
    # only top-2
    assert precision_at_k(retrieved, expected, k=2) == 1.0


def test_mrr_first_rank() -> None:
    assert mean_reciprocal_rank([["a", "b", "c"]], [["a"]]) == 1.0


def test_mrr_second_rank() -> None:
    assert mean_reciprocal_rank([["x", "a", "b"]], [["a"]]) == 0.5


def test_mrr_no_hit() -> None:
    assert mean_reciprocal_rank([["x", "y"]], [["a"]]) == 0.0


def test_mrr_averages_over_queries() -> None:
    # query 1: hit at rank 1 → 1.0
    # query 2: hit at rank 2 → 0.5
    # avg = 0.75
    result = mean_reciprocal_rank(
        retrieved_lists=[["a"], ["x", "b"]],
        expected_lists=[["a"], ["b"]],
    )
    assert result == 0.75
