# Phase 5 Dogfood Report

**Date:** 2026-04-13
**Version:** 0.5.0
**Scope:** Stabilization, hook enforcement, dual-language retrieval, new relation types, value metrics, scan coverage

## Eval gate results

### LV_DCP synthetic (32 queries)
- recall@5 files:    0.964 (target >= 0.92) **PASS**
- precision@3 files: 0.568 (target >= 0.60) **MISS** (regressed from 0.630)
- recall@5 symbols:  0.880 (target >= 0.80) **PASS**
- MRR files:         0.922
- impact_recall@5:   0.931 (target >= 0.85) **PASS**

### Multi-project (9 queries, 4 projects)
- Global recall@5:   0.500 (target >= 0.50) **PASS** (regressed from 0.611)
- Project_Large:    0.200 — large project recall degraded significantly
- Project_Medium_A: 0.750
- Project_Medium_B: 1.000
- Project_Small:   1.000

### Delta from Phase 4
| Metric | Phase 4 | Phase 5 | Delta |
|---|---|---|---|
| recall@5 files | 0.948 | 0.964 | +0.016 |
| precision@3 files | 0.630 | 0.568 | -0.062 |
| recall@5 symbols | 0.880 | 0.880 | 0.000 |
| impact_recall@5 | 0.931 | 0.931 | 0.000 |
| multi-project global | 0.611 | 0.500 | -0.111 |

## What was built

### Hook enforcement (PreToolUse / PostToolUse)
- MCP server instructions now enforce lvdcp_pack before Grep/Read
- CLAUDE.md discipline auto-injected into scanned projects via `ctx scan`
- Stronger wording: BLOCKING REQUIREMENT, not suggestion

### Dual-language retrieval
- 80+ Russian-English term pairs for cross-language query matching
- Improves recall for bilingual codebases (Russian comments, English identifiers)

### New relation types
- `tests_for` — links test files to their subjects
- `inherits` — class inheritance edges
- `specifies` — spec/config references

### Value metrics dashboard
- Packs served counter, compression ratio, coverage quality tracking
- Scan coverage widget: per-project symbol coverage %, language/relation breakdown

### Test suite
- Phase 4 close: ~429 tests
- Phase 5 close: 457 tests, 0 failures

## Known limitations
- precision@3 regressed below 0.60 threshold — recall improvements came at precision cost
- Multi-project recall for large projects (Project_Large) dropped to 0.200 — query reformulation between calibrated and final fixtures exposed weaknesses
- Multi-project eval fixture queries were tightened (English-only) which revealed cross-language gaps the calibrated set masked

## What to address in Phase 6
- Precision recovery: tighter score cutoff or reranking pass
- Large-project multi-project retrieval: Project_Large needs better symbol/FTS coverage
- Cross-language parsers (TS/JS/Go/Rust) may improve multi-project recall for polyglot repos
