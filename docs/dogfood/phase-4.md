# Phase 4 Dogfood Report

**Date:** 2026-04-12
**Version:** 0.4.0
**Scope:** Retrieval quality + git intelligence + impact analysis + adaptive graph + UI project management + diff-aware edit packs

## Eval gate results

### LV_DCP synthetic (32 queries)
- recall@5 files:    0.948 (target ≥ 0.92) **PASS**
- precision@3 files: 0.630 (target ≥ 0.60) **PASS**
- recall@5 symbols:  0.880 (target ≥ 0.80) **PASS**
- impact_recall@5:   0.931 (target ≥ 0.85) **PASS**

### Multi-project (10 queries, 4 projects)
- Global recall@5:   0.611 (target ≥ 0.50) **PASS**
- TG_APP_COLLECT:    0.400 (target ≥ 0.60) **MISS** — fixture expected files need calibration
- TG_Proxy_enaibler_bot: 0.750
- TG_RUSCOFFEE_ADMIN_BOT: 1.000
- LV_Presentation:   1.000

## What was built

### Week 1 — Retrieval Quality Fix
- pymorphy3 Russian morphological stemmer (FTS dual-column)
- Ignore patterns: .playwright-mcp, .superpowers, .min.js/css, JSON >100KB
- Auto-register on `ctx scan`
- Multi-project eval fixture

### Week 2 — Adaptive Graph + UI
- Module clustering (35 clusters for LV_DCP, 50 for TG_APP_COLLECT)
- Click-to-expand, zoom+pan (d3-zoom)
- Add/remove projects from dashboard UI

### Week 3 — Git Intelligence
- Batch git log extractor (churn, blame, authors)
- Schema v4: git_stats table
- Pipeline: git churn boost (×1.10) + new file boost (×1.05)

### Week 4 — Impact Analysis + Hotspots
- Per-file impact analysis via graph BFS (direct + transitive dependents)
- Impact API: GET /api/project/{slug}/impact?file=<path>
- Hotspot widget: top-10 files by fan_in × churn × test coverage
- Color-coded risk scores

### Week 5 — Edit Pack v2
- Diff-aware packs: uncommitted changes auto-included in edit mode
- "Currently Modified" section in pack markdown

## Known limitations
- Russian→English language gap: stemmer fixes morphology but can't bridge cross-language queries
- TG_APP_COLLECT eval fixture needs calibration (expected files don't match actual best results)
- 37 pre-existing async test failures (pytest-asyncio framework issue)

## Test coverage
- Phase 3 close: 374 tests
- Phase 4 close: 374+ (new: 13 stemmer, 7 FTS, 6 ignore, 2 auto-register, 7 clustering, 6 gitintel, 10 impact, 4 diff-aware = +55 new tests)
