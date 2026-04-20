"""Tests for dataset-adaptive vector fusion weighting."""

from __future__ import annotations

from libs.retrieval.pipeline import (
    VECTOR_FULL_CORPUS_SIZE,
    VECTOR_FULL_TOP_SCORE,
    VECTOR_MIN_CORPUS_SIZE,
    VECTOR_MIN_TOP_SCORE,
    compute_vector_fusion_weight,
    rrf_fuse,
)


class TestComputeVectorFusionWeight:
    def test_small_corpus_returns_zero(self) -> None:
        # Below the minimum corpus size the weight is zero regardless of similarity.
        assert (
            compute_vector_fusion_weight(
                corpus_size=50,
                top_vector_score=0.95,
            )
            == 0.0
        )

    def test_low_confidence_top_returns_zero(self) -> None:
        assert (
            compute_vector_fusion_weight(
                corpus_size=10_000,
                top_vector_score=0.30,
            )
            == 0.0
        )

    def test_high_confidence_large_corpus_returns_one(self) -> None:
        assert (
            compute_vector_fusion_weight(
                corpus_size=VECTOR_FULL_CORPUS_SIZE,
                top_vector_score=VECTOR_FULL_TOP_SCORE,
            )
            == 1.0
        )

    def test_midrange_returns_between_zero_and_one(self) -> None:
        w = compute_vector_fusion_weight(
            corpus_size=(VECTOR_MIN_CORPUS_SIZE + VECTOR_FULL_CORPUS_SIZE) // 2,
            top_vector_score=(VECTOR_MIN_TOP_SCORE + VECTOR_FULL_TOP_SCORE) / 2,
        )
        assert 0.0 < w < 1.0

    def test_weight_is_product_of_the_two_axes(self) -> None:
        # Two axes should multiply, not add — either can veto.
        w = compute_vector_fusion_weight(
            corpus_size=VECTOR_FULL_CORPUS_SIZE,
            top_vector_score=(VECTOR_MIN_TOP_SCORE + VECTOR_FULL_TOP_SCORE) / 2,
        )
        # Score at midpoint gives ~0.5 on the score axis; size axis is 1.0.
        assert 0.4 < w < 0.6


class TestRrfFuseWeights:
    def test_zero_weight_disables_ranking(self) -> None:
        a = {"x": 1.0, "y": 0.5}
        b = {"z": 1.0, "x": 0.9}
        fused_equal = rrf_fuse([a, b])
        fused_zero = rrf_fuse([a, b], weights=[1.0, 0.0])
        # Zero-weighted ranking contributes nothing; its keys missing from a stay out.
        assert "z" in fused_equal
        assert "z" not in fused_zero

    def test_weights_scale_contribution(self) -> None:
        a = {"x": 1.0, "y": 0.5}
        b = {"z": 1.0}
        half = rrf_fuse([a, b], weights=[1.0, 0.5])
        full = rrf_fuse([a, b], weights=[1.0, 1.0])
        # z only appears in b — scaling b by 0.5 halves z's fused score.
        assert half["z"] < full["z"]

    def test_mismatched_weights_length_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="weights length"):
            rrf_fuse([{"a": 1.0}, {"b": 1.0}], weights=[1.0])

    def test_default_weights_preserve_original_behavior(self) -> None:
        a = {"x": 1.0}
        b = {"y": 1.0}
        unweighted = rrf_fuse([a, b])
        explicit_equal = rrf_fuse([a, b], weights=[1.0, 1.0])
        assert unweighted == explicit_equal
