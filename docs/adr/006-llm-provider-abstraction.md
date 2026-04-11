# ADR-006: LLM Provider Abstraction

**Status:** Accepted
**Date:** 2026-04-11
**Supersedes:** —
**Relates to:** ADR-001 (cost budgets), ADR-004 (Phase 2 pivot)

## Context

Phase 3c introduces LLM-driven summaries and (in 3c.2) rerank. The project previously assumed Claude API as the sole provider. Two constraints force a rethink:

1. **Max subscription is not API access.** Claude Max ($100/mo) covers Claude Code chat usage but not programmatic API calls. LLM pipeline would create a second, separately-billed Anthropic account.
2. **Cost is provider-dependent.** OpenAI GPT-4o-mini is ~10× cheaper than Claude Sonnet 4.6 for the same per-file summary workload. Locking to one provider means overpaying when a cheaper equivalent exists.
3. **Privacy-conscious users want local inference.** Ollama-backed Llama/Qwen2.5-Coder models run entirely offline, zero cost, at the price of latency and quality gap.

## Decision

LV_DCP introduces `libs/llm/` — a pluggable provider abstraction. One `LLMClient` Protocol, three concrete implementations: `OpenAIClient` (default), `AnthropicClient`, `OllamaClient`. Provider selection is runtime configuration via `~/.lvdcp/config.yaml:llm.provider`.

### Key choices

1. **Default provider: OpenAI, default model: `gpt-4o-mini`.** Cheapest production-grade option in 2026-04 pricing. LV_DCP canary (500 files) summarizes for ~$0.15, well under the ≤$0.50 ADR-001 budget.
2. **API keys via env vars only.** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. Never stored in `config.yaml` — users can safely commit their dotfiles without leaking credentials. Config file stores only the env var *name*, not the value.
3. **Cost tracking is per-provider.** `libs/llm/cost.py` holds a static pricing table per known model. Adding a new model = one PR to the table. Runtime cost is computed deterministically from `UsageRecord` returned by each adapter.
4. **Budget enforcement is soft in 3c.1.** `ctx mcp doctor` WARN at 80%, FAIL at 100%. Dashboard widget color-codes. No hard-stop on API calls — that's a Phase 5+ possibility if abuse materializes.
5. **Summary cache key includes `model_name`.** Two different models produce two different summaries for the same file. Switching provider does not invalidate existing cache for the previous provider.

## Alternatives considered

1. **Single provider (Claude API only).** Rejected: locks users into Anthropic billing, breaks zero-cost path, 10× more expensive than OpenAI GPT-4o-mini for equivalent quality on summaries.
2. **Claude API + Ollama only (no OpenAI).** Rejected: Claude API pricing exceeds ADR-001 ≤$0.50 budget on 500-file canary without extensive Haiku tiering. OpenAI is simpler.
3. **LiteLLM or similar unified gateway.** Rejected: adds a heavy runtime dependency and a single point of failure. Three ~200-line adapters are simpler to debug and own.
4. **Hardcoded provider with config switch.** Rejected: violates the spirit of "pluggable" — users can't add a fourth provider (e.g., Groq, Fireworks) without modifying core code. Protocol-based abstraction makes extension additive.

## Consequences

### Positive

- Users can switch providers without changing code.
- Zero-cost path available for privacy-conscious users or those without an API budget (Ollama).
- Cost tracking becomes a first-class citizen via `libs/llm/cost.py`.
- Single `LLMClient` Protocol means Phase 3c.2's rerank lands additively — one new method in three files, no refactor.

### Negative

- ~200 extra lines of code vs single-provider approach (three adapters + registry + cost table).
- Tests must cover all three providers (mocked), ~3× the test volume for LLM layer.
- Pricing table needs manual updates when providers change rates (expected ~quarterly).

### Operational

- `ctx mcp doctor` gains checks 8 (provider health) and 9 (budget status).
- Dashboard `/settings` page lets users switch provider without editing YAML.
- README documents env var setup per provider.

## Related

- Spec: [docs/superpowers/specs/2026-04-11-phase-3c1-design.md](../superpowers/specs/2026-04-11-phase-3c1-design.md)
- Budget table: [ADR-001](001-budgets.md)
