"""Static pricing tables + cost calculation for all supported LLM models."""

from __future__ import annotations

from libs.llm.errors import LLMConfigError
from libs.llm.models import ModelSpec

MODELS: dict[str, ModelSpec] = {
    # OpenAI
    "gpt-4o-mini": ModelSpec(
        name="gpt-4o-mini",
        provider="openai",
        context_window=128_000,
        pricing_input_per_mtok=0.15,
        pricing_output_per_mtok=0.60,
        pricing_cache_read_per_mtok=0.075,
    ),
    "gpt-5-mini": ModelSpec(
        name="gpt-5-mini",
        provider="openai",
        context_window=400_000,
        pricing_input_per_mtok=0.25,
        pricing_output_per_mtok=2.00,
        pricing_cache_read_per_mtok=0.025,
    ),
    "gpt-5": ModelSpec(
        name="gpt-5",
        provider="openai",
        context_window=400_000,
        pricing_input_per_mtok=1.25,
        pricing_output_per_mtok=10.00,
        pricing_cache_read_per_mtok=0.125,
    ),
    # Anthropic
    "claude-haiku-4-5": ModelSpec(
        name="claude-haiku-4-5",
        provider="anthropic",
        context_window=200_000,
        pricing_input_per_mtok=0.80,
        pricing_output_per_mtok=4.00,
        pricing_cache_read_per_mtok=0.08,
    ),
    "claude-sonnet-4-6": ModelSpec(
        name="claude-sonnet-4-6",
        provider="anthropic",
        context_window=1_000_000,
        pricing_input_per_mtok=3.00,
        pricing_output_per_mtok=15.00,
        pricing_cache_read_per_mtok=0.30,
    ),
    # Ollama (always free)
    "qwen2.5-coder:32b": ModelSpec(
        name="qwen2.5-coder:32b",
        provider="ollama",
        context_window=32_768,
        pricing_input_per_mtok=0.0,
        pricing_output_per_mtok=0.0,
    ),
    "qwen2.5-coder:7b": ModelSpec(
        name="qwen2.5-coder:7b",
        provider="ollama",
        context_window=32_768,
        pricing_input_per_mtok=0.0,
        pricing_output_per_mtok=0.0,
    ),
    "llama3.3:70b": ModelSpec(
        name="llama3.3:70b",
        provider="ollama",
        context_window=128_000,
        pricing_input_per_mtok=0.0,
        pricing_output_per_mtok=0.0,
    ),
}


def calculate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Compute USD cost for a single LLM call.

    Raises LLMConfigError if *model* is not in the MODELS table.
    """
    if model not in MODELS:
        raise LLMConfigError(f"unknown model: {model!r}")
    spec = MODELS[model]
    regular_input = max(0, input_tokens - cached_input_tokens)
    cost = (
        regular_input * spec.pricing_input_per_mtok / 1_000_000
        + cached_input_tokens * spec.pricing_cache_read_per_mtok / 1_000_000
        + output_tokens * spec.pricing_output_per_mtok / 1_000_000
    )
    return round(cost, 8)
