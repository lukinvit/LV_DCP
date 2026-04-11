"""Heuristic over retrieval score distribution to flag ambiguous results."""

from __future__ import annotations

from typing import Literal

Coverage = Literal["high", "medium", "ambiguous"]


def _ratio(sorted_scores: list[float]) -> float:
    """Return top / tail ratio, where tail is 4th place (or last if <4 items)."""
    top = sorted_scores[0]
    tail = sorted_scores[3] if len(sorted_scores) >= 4 else sorted_scores[-1]
    if tail <= 0:
        return float("inf")
    return top / tail


def compute_coverage(scores: dict[str, float]) -> Coverage:
    """Classify the retrieval score distribution.

    - high: top score >= 2x fourth-place score, OR single result
    - medium: top score > 1.2x fourth-place score
    - ambiguous: flat distribution, empty, or fewer than 4 but not clear winner
    """
    if not scores:
        return "ambiguous"

    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) == 1 or sorted_scores[0] <= 0:
        return "high" if sorted_scores[0] > 0 else "ambiguous"

    ratio = _ratio(sorted_scores)
    if ratio >= 2.0:
        return "high"
    if ratio >= 1.2:
        return "medium"
    return "ambiguous"
