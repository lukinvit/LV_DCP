"""Unit tests for libs/eval/cost_guard (see specs/006-ragas-promptfoo-eval)."""

from __future__ import annotations

import pytest
from libs.eval.cost_guard import CostGuard, CostGuardExceeded


def test_cost_guard_accumulates_spend() -> None:
    guard = CostGuard(max_usd=1.0)
    cost = guard.incur(tokens_in=1000, tokens_out=500, model="claude-haiku-4-5")
    assert cost > 0
    assert guard.spent_usd == pytest.approx(cost)
    assert guard.remaining_usd == pytest.approx(1.0 - cost)


def test_cost_guard_raises_when_over_budget() -> None:
    # claude-haiku-4-5 is $0.80/MTok input, $4.00/MTok output.
    # 1M input + 1M output = $4.80 — well over $1 budget.
    guard = CostGuard(max_usd=1.0)
    with pytest.raises(CostGuardExceeded) as exc:
        guard.incur(tokens_in=1_000_000, tokens_out=1_000_000, model="claude-haiku-4-5")
    assert exc.value.max_usd == 1.0
    assert exc.value.spent_usd > 1.0
    # Call was not recorded on rejection.
    assert guard.spent_usd == 0.0


def test_cost_guard_stays_under_budget_across_multiple_calls() -> None:
    guard = CostGuard(max_usd=0.10)
    for _ in range(5):
        guard.incur(tokens_in=1_000, tokens_out=200, model="claude-haiku-4-5")
    assert guard.spent_usd < 0.10


def test_cost_guard_rejects_invalid_max_usd() -> None:
    with pytest.raises(ValueError):
        CostGuard(max_usd=0.0)
    with pytest.raises(ValueError):
        CostGuard(max_usd=-1.0)


def test_cost_guard_unknown_model_raises() -> None:
    from libs.llm.errors import LLMConfigError

    guard = CostGuard(max_usd=1.0)
    with pytest.raises(LLMConfigError):
        guard.incur(tokens_in=100, tokens_out=100, model="nonexistent-model")


def test_cost_guard_remaining_never_negative() -> None:
    guard = CostGuard(max_usd=1.0)
    assert guard.remaining_usd == 1.0
    guard.incur(tokens_in=100, tokens_out=100, model="claude-haiku-4-5")
    assert guard.remaining_usd >= 0.0
