# Phase 3c.1 Dogfood Report

**Date:** 2026-04-11
**Tag:** phase-3c1-complete (pending)
**Version:** 0.3.2
**Author:** Vladimir Lukin

## Exit criterion verification

Script: [scripts/phase-3c1-dogfood.sh](../../scripts/phase-3c1-dogfood.sh)
Full log: `/tmp/phase-3c1-dogfood.log`

### ctx summarize cost per project

| Project | Files | New summaries | Cached | Cost USD | Tokens in→out | Latency |
|---|---|---|---|---|---|---|
| LV_DCP | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> |
| TG_Proxy_enaibler_bot | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> |
| TG_RUSCOFFEE_ADMIN_BOT | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> |

### Cache hit rate on second run

Re-run `ctx summarize` on the same projects — expect 100% cache hits, $0 cost, <5s per project.

| Project | Cache hits / total | Cost | Time |
|---|---|---|---|
| LV_DCP | <todo> / <todo> | $0.0000 | <todo> |
| TG_Proxy_enaibler_bot | <todo> / <todo> | $0.0000 | <todo> |
| TG_RUSCOFFEE_ADMIN_BOT | <todo> / <todo> | $0.0000 | <todo> |

### ctx mcp doctor output

Expected: **9 checks**, 8-9 PASS after env var + install.

```
<paste output here>
```

### Sample summaries (manual quality check)

5 random summaries from LV_DCP — verify they're technically correct:

1. `libs/retrieval/pipeline.py`: _<paste>_
2. `libs/claude_usage/reader.py`: _<paste>_
3. `apps/ui/routes/index.py`: _<paste>_
4. `libs/mcp_ops/doctor.py`: _<paste>_
5. `libs/llm/cost.py`: _<paste>_

### UI /settings page smoke test

- `ctx ui` starts cleanly
- Navigate to `/settings` → form loads
- Select provider dropdown → options visible (openai, anthropic, ollama)
- Test connection button works (when OPENAI_API_KEY is set) → ✓ or ✗ feedback
- Save settings → persists to `~/.lvdcp/config.yaml`
- Budget widget on index page shows monthly spend (if available)

| Test | Status | Notes |
|---|---|---|
| Page loads | <todo> | |
| Form saves | <todo> | |
| Test connection | <todo> | |
| Budget widget renders | <todo> | |

## Changed surface

- `libs/llm/` — new pluggable LLM provider package (openai + anthropic + ollama adapters)
- `libs/summaries/` — file-level summary generator with sqlite cache
- `libs/status/budget.py` — monthly budget aggregator
- `libs/core/projects_config.py` — extended with `LLMConfig`
- `libs/mcp_ops/doctor.py` — 2 new checks (provider + budget)
- `apps/mcp/tools.py` — `lvdcp_status` gains `budget` field
- `apps/cli/commands/summarize.py` — new `ctx summarize` command
- `apps/ui/routes/settings.py` — `/settings` page
- `apps/ui/templates/settings.html.j2`, `partials/budget_widget.html.j2`
- `pyproject.toml` — `openai>=1.50`, `anthropic>=0.40`, `tiktoken>=0.7`
- Version bump: 0.3.1 → 0.3.2
- `docs/adr/006-llm-provider-abstraction.md`

## Cost / latency on canary repo (LV_DCP)

| Metric | Phase 3b close | Phase 3c.1 close | Delta | Notes |
|---|---|---|---|---|
| cold scan (full) | 0.83s | <todo> | <todo> | no retrieval changes |
| warm scan | 0.52s | <todo> | <todo> | no retrieval changes |
| ctx summarize (cold) | — | <todo> | new | gpt-4o-mini on N files |
| ctx summarize (warm) | — | <todo> | new | 100% cache hit expected |
| files / symbols / relations_cached | 215 / 1573 / 4228 | <todo> | <todo> | may grow if libs/llm added symbols |
| `ctx mcp doctor` (9 checks) | — | <todo> | new | includes provider + budget checks |

**Summary:** Retrieval pipeline untouched. Scan latency should stay comparable to Phase 3b close (±5%). Doctor gains 2 new checks (≈100ms each).

## Eval metrics (must stay identical — retrieval untouched)

| Metric | Threshold | Phase 3b close | Phase 3c.1 close |
|---|---|---|---|
| recall@5 files | ≥ 0.85 | 0.891 | <todo> |
| precision@3 files | ≥ 0.60 | 0.620 | <todo> |
| recall@5 symbols | ≥ 0.80 | 0.833 | <todo> |
| impact_recall@5 | ≥ 0.75 | 0.819 | <todo> |

**Acceptance criterion:** All four metrics must equal Phase 3b close values (zero regression). Retrieval code path untouched by Phase 3c.1.

## Test suite

- Phase 3b close: 278 passed
- Phase 3c.1 close: <todo> (target ≥ 310)
- `make lint typecheck test`: <todo>

Breakdown of new tests (expected):
- `tests/unit/llm/` — cost, registry, openai, anthropic, ollama adapters (~25 tests)
- `tests/unit/summaries/` — store, generator, pipeline (~15 tests)
- `tests/unit/status/test_budget.py` — budget computation (~8 tests)
- `tests/unit/core/test_projects_config_llm.py` — LLMConfig schema (~4 tests)
- `tests/integration/test_ctx_summarize.py` — CLI end-to-end (~6 tests)
- `tests/integration/test_ui_settings.py` — /settings route (~5 tests)
- `tests/integration/test_lvdcp_status_budget.py` — MCP + budget (~3 tests)

## Upgrade smoke test

- From `phase-3b-complete`: `git pull && uv sync --all-extras && ctx mcp doctor` → <todo>
- After `ctx mcp install`: doctor clean (9/9 checks pass with default config), `ctx ui` starts, /settings page accessible
- OPENAI_API_KEY env var set → `ctx summarize` works, `ctx ui /settings` shows budget widget

## Known issues

- <todo>

## Next up: Phase 3c.2

Vector search (BGE-M3 embeddings + sqlite-vec) + listwise rerank stage. Will use the now-cached summaries from 3c.1 as embedding inputs. Targets: recall@5 files ≥ 0.92, impact_recall@5 ≥ 0.85.
