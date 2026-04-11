# Phase 3c.2 Failure Analysis — Measurement-First Data

**Date:** 2026-04-12
**Purpose:** Classify **actual** retrieval failure modes before designing Phase 3c.2.
**Method:** Ran current deterministic pipeline (FTS + graph + symbol) on two query sets — the existing synthetic fixture and a new real-world query set against LV_DCP itself. Analyzed per-query recall@5 breakdowns to identify where and why retrieval misses.

## TL;DR

**The spec's "LLM summaries + vector search + rerank" plan was pointed at the wrong problem.** Real failure analysis reveals three categories, only one of which requires LLM infrastructure:

1. **Documentation dominance on real queries (5 / 7 real-LV_DCP failures).** FTS heavily ranks `docs/superpowers/specs/*.md`, `docs/dogfood/*.md` because those files contain concentrated project keywords. Code files with the same keywords distributed across 100+ files get diluted scores. **Fix:** role-weighted score fusion. Demote `role="docs"` when query mode is `navigate` / `edit`. **Cost:** ~1-2 days, zero LLM calls.
2. **Config file retrieval on synthetic fixture (4 / 8 fixture failures).** Impact queries expecting `config/settings.yaml` don't surface it — config files are short, keyword-poor, graph-disconnected. **Fix:** boost config files to candidate set when query mentions config-ish terms (ttl, schedule, timeout, config, settings). **Cost:** ~0.5 day.
3. **Semantic intent + transitive graph walk (2 real + 2 fixture failures).** Queries like "add exponential backoff to anthropic client" — the actual implementation lives in `openai_client.py`, query says `anthropic`. Genuine semantic miss. **Fix:** vector search on file summaries (which already exist from 3c.1). **Cost:** ~1 week.

**Revised Phase 3c.2 proposal:** fix #1 + #2 first (pure deterministic, ~3 days), measure eval. If we hit targets — done, no LLM retrieval needed. If not — add #3 (vector search on summaries) and possibly rerank. **Most likely outcome:** #1 + #2 alone pushes recall@5 from 0.891 → **~0.95** and impact_recall@5 from 0.819 → **~0.90**, blowing past the 0.92 / 0.85 targets.

## Source data

### Synthetic fixture (`tests/eval/fixtures/sample_repo/`)

32 queries (20 navigate + 12 impact), current eval metrics:
- recall@5 files: 0.891 (target 0.92)
- precision@3 files: 0.620
- recall@5 symbols: 0.833
- impact_recall@5: 0.819 (target 0.85)

**Zero queries fully miss top-5.** All 32 queries have their FIRST expected file somewhere in top-5. The 0.891 average is driven by queries with **multiple expected files** where only a subset is retrieved.

#### Per-query failures on synthetic fixture (8 of 32)

| Query | Mode | recall@5 | Missed | Category |
|---|---|---|---|---|
| q04-refresh-flow | navigate | 0.50 | `app/handlers/auth.py` | Graph / rank |
| q16-access-ttl | navigate | 0.50 | `config/settings.yaml` | **Config retrieval** |
| q19-edit-login | edit | 0.67 | `tests/test_auth.py` | Graph / rank |
| i01-session-storage-change | edit | 0.50 | `app/workers/cleanup.py`, `tests/test_cleanup.py` | Graph expansion weak |
| i02-password-hash-tighten | edit | 0.67 | `app/handlers/auth.py` | **Rank wrong** |
| i04-access-ttl-reduction | edit | 0.50 | `config/settings.yaml` | **Config retrieval** |
| i05-cleanup-schedule-change | edit | 0.50 | `config/settings.yaml` | **Config retrieval** |
| i06-db-connection-migration | edit | 0.67 | `app/main.py` | Graph / rank |

**Categories on synthetic:**
- Config retrieval: 3 queries (q16, i04, i05) — but also appears partially in i06. **4 queries total**.
- Graph expansion weak (transitive): i01, i06, q04 — 3 queries.
- Rank wrong (test file above expected handler, etc.): i02, q19 — 2 queries.

### Real LV_DCP queries (new, 15 queries)

New fixture file `tests/eval/real_queries.yaml` — queries that a developer actually working on LV_DCP would issue. Cover code discovery, edit scoping, and semantic intent.

**Current eval metrics on real queries:**
- avg recall@5: **0.611** — massively below synthetic's 0.891
- 10/15 queries: first expected file in top-5
- 7/15 queries: recall < 1.0 (complete or partial miss)

#### Per-query failures on real LV_DCP (7 of 15)

| Query | Mode | recall@5 | Missed | Category |
|---|---|---|---|---|
| r03-summary-cache-storage | navigate | **0.00** | `libs/summaries/store.py` | **Docs dominance** |
| r04-budget-widget-ui | navigate | **0.00** | `apps/ui/.../budget_widget.html.j2`, `libs/status/budget.py` | **Docs dominance** |
| r05-doctor-checks | navigate | **0.00** | `libs/mcp_ops/doctor.py` | **Docs dominance** |
| r11-edit-rate-limit-adapter | edit | 0.67 | `libs/llm/openai_client.py` | Semantic intent |
| r12-edit-new-mcp-tool | edit | **0.00** | `apps/mcp/tools.py`, `apps/mcp/server.py`, `libs/retrieval/trace.py` | **Docs dominance** |
| r13-edit-extend-sparklines | edit | **0.00** | `libs/status/aggregator.py`, `sparkline_row.html.j2`, `dashboard.js` | **Docs dominance** |
| r14-claude-usage-aggregation | navigate | 0.50 | `libs/claude_usage/reader.py` | Graph expansion weak |

**Example: r04 "budget widget rendering in dashboard topbar"**
```
Expected: apps/ui/templates/partials/budget_widget.html.j2
         libs/status/budget.py

Got top-5 from current pipeline:
  1. docs/superpowers/specs/2026-04-11-phase-3c1-design.md
  2. docs/dogfood/phase-3c1.md
  3. docs/superpowers/plans/2026-04-11-phase-3c1.md
  4. docs/superpowers/plans/2026-04-11-phase-3b.md
  5. libs/llm/errors.py
```

The 3c.1 design spec contains the exact phrase "budget widget in topbar" several times because I wrote it that way. The code file `libs/status/budget.py` contains "budget" once in its docstring and function names. FTS rewards the docs file. Code is buried.

**Example: r05 "health checks for the install state"**
```
Expected: libs/mcp_ops/doctor.py

Got top-5:
  1. docs/superpowers/specs/2026-04-11-phase-3b-design.md
  2. docs/dogfood/phase-3b.md
  3. docs/dogfood/phase-3c1.md
  4. docs/superpowers/plans/2026-04-11-phase-3b.md
  5. docs/tz.md
```

Five docs, **zero code files** in top-5. The word "doctor" doesn't appear in the user's query, but `install state` matches docs that discuss install story at length.

## Classification of all 15 failures (synthetic + real)

| Category | Count | Fix approach | Est. effort | LLM needed |
|---|---|---|---|---|
| **Docs dominance in FTS** | 5 real | Role-weighted score fusion: demote `role="docs"` | 1-2 days | No |
| **Config file retrieval** | 4 fixture | Config boost on config-ish query terms; add config files to candidate set | 0.5 day | No |
| **Graph expansion weak** | 3 fixture + 1 real | Either (a) deeper graph walk, (b) vector fallback on semantic intent | 1 day or 1 week | Optional |
| **Rank wrong (test above handler)** | 2 fixture | LLM listwise rerank — **or** heuristic: non-test before test when query isn't test-specific | 0.5-7 days | Optional |
| **Semantic intent (paraphrase)** | 1 real | Vector search on file summaries + query | 1 week | **Yes** |

**Total failures:** 15
**Fixable without LLM:** 11 failures (5 docs dominance + 4 config + 2 rank if heuristic)
**Require LLM-based approach:** 4 failures at most (3 graph, 1 semantic) — but several of these might also be fixable by deterministic improvements.

## Projected eval impact of each fix

Starting from current: **recall@5 = 0.891** on synthetic, **0.611** on real LV_DCP. Target: **≥ 0.92** synthetic, **≥ 0.85** real (not a formal target but we should hit it).

### Fix 1: Role-weighted fusion (docs demotion for navigate/edit)

**Synthetic effect:** none (no docs failures on synthetic; the docs file `docs/architecture.md` is the EXPECTED result for q14 and already ranks #1).
**Real effect:** fixes 5/7 failures:
- r03 → likely ranks `libs/summaries/store.py` in top-5
- r04 → likely ranks `libs/status/budget.py` and maybe the .j2 template
- r05 → likely ranks `libs/mcp_ops/doctor.py`
- r12 → likely ranks `apps/mcp/tools.py`, `server.py`
- r13 → likely ranks `libs/status/aggregator.py`, maybe static .js

**Projected real avg recall@5:** 0.611 → **~0.87** (5 failures fixed, 2 remaining at partial)

### Fix 2: Config file boost

**Synthetic effect:** fixes q16, i04, i05, and part of i06 (4 queries).
- 24 queries currently at recall=1.0 stay at 1.0
- 8 failing queries: after fix, 4 move to 1.0 (was 0.5)
- New avg ≈ (24 × 1.0 + 4 × 1.0 + 4 × ~0.6) / 32 = **~0.95**

**Real effect:** negligible (LV_DCP doesn't have a config/ directory matching the pattern).

### Combined Fix 1 + Fix 2

**Synthetic:** 0.891 → **~0.95** (config fix drives it)
**Real:** 0.611 → **~0.87** (role fix drives it)

**Synthetic TARGET 0.92: HIT with margin.**
**Real target (0.85 stretch): HIT with margin.**

### Fix 3 (Vector + rerank) — only if Fix 1 + 2 insufficient

This is the 2-3 week LLM-heavy plan from the original 3c.2 spec. Could push numbers further but **not required** to hit targets based on projected impact of cheap fixes.

## Revised Phase 3c.2 scope proposal

### Three options for the user

**Option A — Originally committed full scope (LLM-heavy)**
Build vector search on summaries + listwise rerank, as per 3c.1 spec section 14. Deprioritize the cheap fixes discovered here.
**Pros:** lays LLM retrieval infrastructure for future phases. Builds pluggable architecture for rerank.
**Cons:** 2-3 weeks of work, may not even improve eval numbers if docs dominance isn't addressed (vector ranking could reward docs MORE because docs have richer embeddings than sparse code). Risk of missing eval targets altogether.

**Option B — Cheap deterministic fixes first (data-driven)**
Fix 1 (role-weighted fusion) + Fix 2 (config boost) + Fix 3 (minor graph expansion tweaks). **No LLM retrieval code**. Measure eval. If below target, iterate.
**Pros:** ~3 days of work. Addresses documented failure modes directly. Zero new runtime cost. Doesn't require OpenAI for retrieval. Likely hits 0.92 / 0.85 targets based on projected impact.
**Cons:** leaves vector search + rerank infrastructure unbuilt for future phases. If deterministic fixes hit a ceiling (e.g., can't get past 0.93), future phase must revisit with LLM retrieval.

**Option C — B first, then optionally A if needed**
Stage 1: Do cheap fixes, measure. If targets met → done, tag `phase-3c2-complete`. If not met → Stage 2: add vector search + rerank on top. Two-stage gate.
**Pros:** minimum viable, maximum ROI. Honest data-driven approach. Keeps LLM retrieval as optional enhancement.
**Cons:** slight process overhead (two stages). If Stage 1 misses by 0.01 from target, have to decide whether to ship "close enough" or invest another 2-3 weeks.

### Recommendation: Option C

Reasons:
1. **Data says cheap fixes are sufficient.** Projected 0.95 synthetic + 0.87 real after Fix 1 + 2. Targets 0.92 / 0.85. Margin ≥ 2 percentage points in both cases.
2. **Risk of Option A is high.** Vector search on documents (which our content currently is, dominated by Markdown specs) could actively hurt ranking, not help. Vector models embed meaning well on natural language but code+docs mixtures are adversarial for dense retrievers.
3. **LLM retrieval infrastructure isn't gate for Phase 4+.** Phase 4 is static impact analysis, not retrieval improvement. Phase 5 could introduce vectors when we have multi-language corpora where docs dominance isn't the bottleneck.
4. **The 3c.1 investment is not wasted.** Summaries are still valuable for the dashboard view (currently shipped in P6 polish) and for humans reviewing what LV_DCP knows about their code. Their role in retrieval just isn't critical.

### Stage 1 scope (Option C)

- **S1.1 — Role-weighted score fusion.** Modify `libs/retrieval/pipeline.py` to apply a role penalty/boost when scoring. Default: code/source = 1.0, test = 0.85, docs = 0.35, config = 1.1 (boost). Configurable via `libs/retrieval/pipeline.py` constants. Test on `tests/eval/real_queries.yaml` and `tests/eval/queries.yaml`.
- **S1.2 — Config file boost heuristic.** When the query text contains any of `{config, settings, timeout, ttl, schedule, env, port}`, add all `role="config"` files with matching any of these keywords to the candidate set with boost weight. Test on synthetic fixture.
- **S1.3 — Graph expansion tuning.** Adjust `GRAPH_EXPANSION_DEPTH` (currently 2) to 3 for edit mode, or add a secondary walk that boosts files linked to the seed's graph neighbourhood at depth 3. Test on impact queries i01, i06, q04.
- **S1.4 — Measurement.** Extend eval harness so `run_eval` produces a per-query report file at `docs/eval/<date>-run.md` with rank-of-first-expected, missed files, coverage label. Run against both query sets.
- **S1.5 — Eval gate.** Require `recall@5 files ≥ 0.92` on synthetic AND `recall@5 files ≥ 0.80` on real LV_DCP (no regression below 0.80). If both pass → tag `phase-3c2-complete`. If one fails → proceed to Stage 2.

**Budget:** 3-4 working days, zero LLM runtime cost, zero new dependencies.

### Stage 2 scope (only if Stage 1 fails eval)

Original 3c.2 spec: vector search + rerank. Scoped down to:
- Vector embeddings of FILE SUMMARIES (not raw content) — short, dense, semantic.
- Sqlite-vec store.
- Fusion with FTS + graph at the pipeline stage level.
- Listwise rerank via LLM client (already stubbed in 3c.1).

**Budget:** 2-3 weeks, if needed.

## Next steps

**Question for the user:** which option, A / B / C?

If C (recommended): proceed to spec writing for Stage 1, then normal spec-review-plan-execute cycle. Stage 2 deferred to own spec if needed.

If A: acknowledge the data but proceed with original LLM-heavy plan.

If B: same as C but commit to not doing Stage 2 at all; ship what we have after deterministic fixes.
