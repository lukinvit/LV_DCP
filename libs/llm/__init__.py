"""Pluggable LLM provider abstraction for LV_DCP.

Exports:
- `LLMClient` protocol (implementations: OpenAIClient, AnthropicClient, OllamaClient)
- `create_client(config: LLMConfig) -> LLMClient` factory
- Error types: `LLMConfigError`, `LLMProviderError`, `BudgetExceededError`
- DTOs: `ModelSpec`, `UsageRecord`, `SummaryResult`, `RerankCandidate`, `RerankResult`
- Cost helpers: `MODELS`, `calculate_cost`
"""
