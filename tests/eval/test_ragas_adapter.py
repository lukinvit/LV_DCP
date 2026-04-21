"""Unit tests for libs/eval/ragas_adapter (see specs/006-ragas-promptfoo-eval).

LLM is mocked at the RAGAS metric level — no real Anthropic call. We assert
that each metric is invoked with the right fields, that the cost guard is
incremented, that the per-query LRU cache returns identical values for
repeated samples, and that missing fields skip the relevant metric.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from libs.eval.cost_guard import CostGuard, CostGuardExceeded
from libs.eval.ragas_adapter import RagasAdapter, RagasQuerySample
from ragas.llms.base import InstructorBaseRagasLLM


def _fake_llm() -> MagicMock:
    """A MagicMock that passes ragas' isinstance(InstructorBaseRagasLLM) check."""
    return MagicMock(spec=InstructorBaseRagasLLM)


def _metric_result(value: float) -> MagicMock:
    """Build a ragas MetricResult stand-in exposing only .value."""
    r = MagicMock()
    r.value = value
    return r


@pytest.fixture
def adapter_with_stubs() -> tuple[RagasAdapter, dict[str, AsyncMock]]:
    """Build an adapter with its 3 metric .ascore methods replaced by mocks.

    We inject ``llm_override=MagicMock()`` so no real anthropic client is
    constructed; then we patch each metric instance's ``ascore`` to avoid
    touching RAGAS internals.
    """
    guard = CostGuard(max_usd=10.0)
    adapter = RagasAdapter(
        judge_model="claude-haiku-4-5",
        cost_guard=guard,
        api_key="dummy",
        llm_override=_fake_llm(),
        cache_enabled=True,
    )
    cp_mock = AsyncMock(return_value=_metric_result(0.8))
    cr_mock = AsyncMock(return_value=_metric_result(0.7))
    f_mock = AsyncMock(return_value=_metric_result(0.9))
    adapter._cp.ascore = cp_mock  # type: ignore[method-assign]
    adapter._cr.ascore = cr_mock  # type: ignore[method-assign]
    adapter._f.ascore = f_mock  # type: ignore[method-assign]
    return adapter, {"cp": cp_mock, "cr": cr_mock, "f": f_mock}


async def test_all_three_metrics_called_when_sample_complete(
    adapter_with_stubs: tuple[RagasAdapter, dict[str, AsyncMock]],
) -> None:
    adapter, mocks = adapter_with_stubs
    sample = RagasQuerySample(
        query_id="q1",
        user_input="What is LV_DCP?",
        retrieved_contexts=["LV_DCP is a context platform"],
        response="a local context platform",
        reference="Local-first engineering memory",
    )
    result = await adapter.run([sample])
    mocks["cp"].assert_awaited_once()
    mocks["cr"].assert_awaited_once()
    mocks["f"].assert_awaited_once()
    assert result.context_precision == 0.8
    assert result.context_recall == 0.7
    assert result.faithfulness == 0.9
    assert result.per_query[0].query_id == "q1"
    assert result.cache_misses == 3
    assert result.cache_hits == 0


async def test_missing_reference_skips_cp_and_cr(
    adapter_with_stubs: tuple[RagasAdapter, dict[str, AsyncMock]],
) -> None:
    adapter, mocks = adapter_with_stubs
    sample = RagasQuerySample(
        query_id="q1",
        user_input="What is X?",
        retrieved_contexts=["context"],
        response="an answer",
        reference=None,
    )
    result = await adapter.run([sample])
    mocks["cp"].assert_not_awaited()
    mocks["cr"].assert_not_awaited()
    mocks["f"].assert_awaited_once()
    assert result.context_precision is None
    assert result.context_recall is None
    assert result.faithfulness == 0.9


async def test_missing_response_skips_faithfulness(
    adapter_with_stubs: tuple[RagasAdapter, dict[str, AsyncMock]],
) -> None:
    adapter, mocks = adapter_with_stubs
    sample = RagasQuerySample(
        query_id="q1",
        user_input="What is X?",
        retrieved_contexts=["context"],
        response=None,
        reference="gold",
    )
    result = await adapter.run([sample])
    mocks["cp"].assert_awaited_once()
    mocks["cr"].assert_awaited_once()
    mocks["f"].assert_not_awaited()
    assert result.faithfulness is None


async def test_missing_contexts_skips_all(
    adapter_with_stubs: tuple[RagasAdapter, dict[str, AsyncMock]],
) -> None:
    adapter, mocks = adapter_with_stubs
    sample = RagasQuerySample(
        query_id="q1",
        user_input="q",
        retrieved_contexts=[],
        response="a",
        reference="r",
    )
    result = await adapter.run([sample])
    mocks["cp"].assert_not_awaited()
    mocks["cr"].assert_not_awaited()
    mocks["f"].assert_not_awaited()
    assert result.context_precision is None
    assert result.context_recall is None
    assert result.faithfulness is None


async def test_cache_prevents_duplicate_calls(
    adapter_with_stubs: tuple[RagasAdapter, dict[str, AsyncMock]],
) -> None:
    adapter, mocks = adapter_with_stubs
    sample = RagasQuerySample(
        query_id="q1",
        user_input="q",
        retrieved_contexts=["c"],
        response="a",
        reference="r",
    )
    # Same sample twice — second run should hit the cache.
    await adapter.run([sample])
    result = await adapter.run([sample])
    assert mocks["cp"].await_count == 1
    assert mocks["cr"].await_count == 1
    assert mocks["f"].await_count == 1
    assert result.cache_hits == 3
    assert result.cache_misses == 0


async def test_cost_guard_increments_on_each_call() -> None:
    guard = CostGuard(max_usd=10.0)
    adapter = RagasAdapter(
        judge_model="claude-haiku-4-5",
        cost_guard=guard,
        api_key="dummy",
        llm_override=_fake_llm(),
    )
    adapter._cp.ascore = AsyncMock(return_value=_metric_result(0.5))  # type: ignore[method-assign]
    adapter._cr.ascore = AsyncMock(return_value=_metric_result(0.5))  # type: ignore[method-assign]
    adapter._f.ascore = AsyncMock(return_value=_metric_result(0.5))  # type: ignore[method-assign]
    sample = RagasQuerySample(
        query_id="q1",
        user_input="q",
        retrieved_contexts=["c"],
        response="a",
        reference="r",
    )
    await adapter.run([sample])
    # 3 calls x (1500 in + 200 out) at claude-haiku-4-5 pricing.
    assert guard.spent_usd > 0
    # Re-run with cached sample — no new spend.
    before = guard.spent_usd
    await adapter.run([sample])
    assert guard.spent_usd == before


async def test_cost_guard_exceeded_aborts() -> None:
    guard = CostGuard(max_usd=0.000001)  # Essentially zero budget.
    adapter = RagasAdapter(
        judge_model="claude-haiku-4-5",
        cost_guard=guard,
        api_key="dummy",
        llm_override=_fake_llm(),
    )
    adapter._cp.ascore = AsyncMock(return_value=_metric_result(0.5))  # type: ignore[method-assign]
    sample = RagasQuerySample(
        query_id="q1",
        user_input="q",
        retrieved_contexts=["c"],
        response="a",
        reference="r",
    )
    with pytest.raises(CostGuardExceeded):
        await adapter.run([sample])


async def test_multiple_samples_aggregate_via_mean(
    adapter_with_stubs: tuple[RagasAdapter, dict[str, AsyncMock]],
) -> None:
    adapter, mocks = adapter_with_stubs
    # Flip return values between calls.
    mocks["cp"].side_effect = [_metric_result(0.6), _metric_result(1.0)]
    mocks["cr"].side_effect = [_metric_result(0.4), _metric_result(0.8)]
    mocks["f"].side_effect = [_metric_result(0.5), _metric_result(0.9)]
    samples = [
        RagasQuerySample(
            query_id=f"q{i}",
            user_input=f"q{i}",
            retrieved_contexts=[f"c{i}"],
            response=f"a{i}",
            reference=f"r{i}",
        )
        for i in range(2)
    ]
    result = await adapter.run(samples)
    assert result.context_precision == pytest.approx(0.8)
    assert result.context_recall == pytest.approx(0.6)
    assert result.faithfulness == pytest.approx(0.7)
    assert [p.query_id for p in result.per_query] == ["q0", "q1"]


def test_adapter_builds_anthropic_llm_when_no_override() -> None:
    """Exercise the _build_anthropic_llm path without making API calls."""
    guard = CostGuard(max_usd=1.0)
    with patch("libs.eval.ragas_adapter._build_anthropic_llm") as fake:
        fake.return_value = _fake_llm()
        adapter = RagasAdapter(
            judge_model="claude-haiku-4-5",
            cost_guard=guard,
            api_key="real-looking-dummy",
        )
        fake.assert_called_once_with("claude-haiku-4-5", "real-looking-dummy")
        assert adapter._llm is fake.return_value
