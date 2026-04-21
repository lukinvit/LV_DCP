"""Back-compat shim — canonical module is :mod:`libs.eval.metrics`."""

from libs.eval.metrics import (
    impact_recall_at_k,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    "impact_recall_at_k",
    "mean_reciprocal_rank",
    "precision_at_k",
    "recall_at_k",
]
