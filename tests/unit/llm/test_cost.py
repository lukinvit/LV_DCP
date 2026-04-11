from __future__ import annotations

import pytest
from libs.llm.cost import MODELS, calculate_cost
from libs.llm.errors import LLMConfigError


def test_gpt_4o_mini_cost() -> None:
    cost = calculate_cost("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    # 1000 * 0.15/M + 500 * 0.60/M = 0.00015 + 0.0003 = 0.00045
    assert cost == pytest.approx(0.00045, rel=1e-6)


def test_gpt_4o_mini_with_cache_read() -> None:
    cost = calculate_cost(
        "gpt-4o-mini", input_tokens=1000, output_tokens=500, cached_input_tokens=800
    )
    # regular_input = 200, cached = 800
    # 200 * 0.15/M + 800 * 0.075/M + 500 * 0.60/M
    # = 0.00003 + 0.00006 + 0.0003 = 0.00039
    assert cost == pytest.approx(0.00039, rel=1e-6)


def test_ollama_models_cost_zero() -> None:
    cost = calculate_cost("qwen2.5-coder:7b", input_tokens=100_000, output_tokens=50_000)
    assert cost == 0.0


def test_claude_sonnet_cost() -> None:
    cost = calculate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    # 1000 * 3/M + 500 * 15/M = 0.003 + 0.0075 = 0.0105
    assert cost == pytest.approx(0.0105, rel=1e-6)


def test_unknown_model_raises() -> None:
    with pytest.raises(LLMConfigError, match="unknown model"):
        calculate_cost("not-a-real-model", input_tokens=100, output_tokens=50)


def test_models_table_has_all_providers() -> None:
    providers = {spec.provider for spec in MODELS.values()}
    assert {"openai", "anthropic", "ollama"} <= providers


def test_pricing_is_positive_for_paid_models() -> None:
    for name, spec in MODELS.items():
        if spec.provider in ("openai", "anthropic"):
            assert spec.pricing_input_per_mtok > 0, f"{name} input price must be >0"
            assert spec.pricing_output_per_mtok > 0, f"{name} output price must be >0"
