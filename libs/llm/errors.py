"""Exception hierarchy for libs/llm."""

from __future__ import annotations


class LLMConfigError(Exception):
    """Raised when provider configuration is invalid (missing env var, unknown model)."""


class LLMProviderError(Exception):
    """Raised when a provider API call fails (network, auth, rate limit, server error)."""


class BudgetExceededError(Exception):
    """Raised by pipeline when a planned operation would exceed the monthly budget."""
