"""Retrieval evaluation metrics. Pure functions, no I/O.

Contract:
- A "retrieved" list is ordered by retrieval rank, most relevant first.
- An "expected" list is unordered ground truth.
- Both contain opaque string keys (file paths or fq_names) — the caller
  decides what domain they represent.
"""

from __future__ import annotations

from collections.abc import Sequence


def recall_at_k(retrieved: Sequence[str], expected: Sequence[str], *, k: int) -> float:
    """Fraction of expected items that appear in the top-k of retrieved.

    If expected is empty, returns 1.0 (no ground truth can be missed).
    """
    if not expected:
        return 1.0
    top = set(retrieved[:k])
    hits = sum(1 for e in expected if e in top)
    return hits / len(expected)


def precision_at_k(retrieved: Sequence[str], expected: Sequence[str], *, k: int) -> float:
    """Fraction of the top-k retrieved items that are in the expected set.

    If k is 0 or retrieved is empty, returns 0.0.
    """
    if k <= 0:
        return 0.0
    top = list(retrieved[:k])
    if not top:
        return 0.0
    expected_set = set(expected)
    hits = sum(1 for r in top if r in expected_set)
    return hits / len(top)


def mean_reciprocal_rank(
    retrieved_lists: Sequence[Sequence[str]],
    expected_lists: Sequence[Sequence[str]],
) -> float:
    """Mean reciprocal rank of the first expected hit across queries.

    A query contributes 1/rank (1-indexed) for the first expected item found,
    or 0 if none found. The final MRR is the mean over all queries.
    """
    if len(retrieved_lists) != len(expected_lists):
        raise ValueError("retrieved and expected lists differ in length")
    if not retrieved_lists:
        return 0.0
    total = 0.0
    for retrieved, expected in zip(retrieved_lists, expected_lists, strict=True):
        expected_set = set(expected)
        reciprocal = 0.0
        for idx, item in enumerate(retrieved, start=1):
            if item in expected_set:
                reciprocal = 1.0 / idx
                break
        total += reciprocal
    return total / len(retrieved_lists)
