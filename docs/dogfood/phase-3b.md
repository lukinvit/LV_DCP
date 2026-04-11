# Phase 3b Dogfood Report

**Date:** 2026-04-11
**Tag:** phase-3b-complete (pending)
**Version:** 0.3.1
**Author:** Vladimir Lukin

## Exit criterion verification

Script: [scripts/phase-3b-dogfood.sh](../../scripts/phase-3b-dogfood.sh)

### Routes smoke test

| Endpoint | Status | Notes |
|---|---|---|
| `GET /` | <todo> | <todo> |
| `GET /project/lv-dcp` | <todo> | <todo> |
| `GET /api/project/lv-dcp/graph.json` | <todo> | <todo> |
| `GET /api/project/lv-dcp/sparklines.json` | <todo> | <todo> |

### MCP resource smoke test

`await session.call_tool("lvdcp_status", {})` → <todo>

### Browser screenshots

- Index view (multi-project grid): _(add screenshot)_
- LV_DCP detail view (graph + sparklines + health card + usage widget): _(add screenshot)_

## Changed surface

- `libs/scan_history/` — new scan event log (rolling 90d retention)
- `libs/claude_usage/` — `.claude/projects` JSONL reader + incremental cache + aggregator
- `libs/status/` — central aggregator + DTOs + daemon_probe + health
- `apps/ui/` — FastAPI dashboard app + templates + static + routes
- `apps/cli/commands/ui.py` — `ctx ui` Typer command
- `apps/mcp/tools.py` — new `lvdcp_status` MCP resource (5th tool)
- `libs/retrieval/trace.py` — extended retention (30 days / 2000 rows), auto-persist on `ctx pack`
- Dependencies: fastapi, uvicorn, jinja2, httpx (dev)
- Version bump: 0.0.0 → 0.3.1

## Cost / latency on canary repo (LV_DCP)

| Metric | Phase 3a | Phase 3b | Delta |
|---|---|---|---|
| cold scan | 0.46s | <todo> | <todo> |
| warm scan | 0.25s | <todo> | <todo> |
| `ctx ui` cold page load (GET /) | — | <todo> | new |
| `ctx ui` project detail (GET /project/lv-dcp) | — | <todo> | new |
| graph.json response time | — | <todo> | new |

## Eval metrics (must not regress vs Phase 3a close)

| Metric | Threshold | Phase 3a close | Phase 3b close |
|---|---|---|---|
| recall@5 files | ≥ 0.85 | 0.891 | <todo> |
| precision@3 files | ≥ 0.60 | 0.620 | <todo> |
| recall@5 symbols | ≥ 0.80 | 0.833 | <todo> |
| impact_recall@5 | ≥ 0.75 | 0.819 | <todo> |

## Test suite

- Phase 3a close: 225 tests
- Phase 3b close: <todo> tests (target: ≥ 280)
- `make lint typecheck test` <todo>

## Upgrade smoke test

- From `phase-3a-complete`: `git pull && uv sync && ctx mcp doctor` → <todo>
- After `ctx mcp install`: doctor clean, `ctx ui` starts, index renders

## Known issues

- <todo>

## Next up: Phase 3c

LLM enrichment + vector search + rerank. Phase 3b data infrastructure (trace_store extended retention, scan_history, claude_usage) gives Phase 3c the measurement baseline for cost/latency budget enforcement.
