"""Pydantic DTOs shared across all LLM providers."""

from __future__ import annotations

from pydantic import BaseModel


class ModelSpec(BaseModel):
    name: str
    provider: str  # "openai" | "anthropic" | "ollama"
    context_window: int
    pricing_input_per_mtok: float
    pricing_output_per_mtok: float
    pricing_cache_read_per_mtok: float = 0.0


class UsageRecord(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cost_usd: float
    model: str
    provider: str
    timestamp: float
