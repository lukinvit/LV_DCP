# Phase 6 Dogfood Report

**Date:** 2026-04-13
**Version:** 0.6.0
**Scope:** Cross-language parsers (TS/JS/Go/Rust), Qdrant vector store, Obsidian vault sync, VS Code extension MVP, cross-project pattern detection

## Eval gate results

### LV_DCP synthetic (32 queries)
- recall@5 files:    0.964 (target >= 0.92) **PASS**
- precision@3 files: 0.568 (target >= 0.60) **MISS** (carried over from Phase 5; precision recovery deferred to Phase 7)
- recall@5 symbols:  0.880 (target >= 0.80) **PASS**
- MRR files:         0.922
- impact_recall@5:   0.931 (target >= 0.85) **PASS**

### Multi-project (9 queries, 4 projects)
- Global recall@5:   0.500 (target >= 0.50) **PASS**
- Project_Large:    0.200 — large-project recall still needs tuning
- Project_Medium_A: 0.750
- Project_Medium_B: 1.000
- Project_Small:   1.000

### Delta from Phase 5
| Metric | Phase 5 | Phase 6 | Delta |
|---|---|---|---|
| recall@5 files | 0.964 | 0.964 | 0.000 |
| precision@3 files | 0.568 | 0.568 | 0.000 |
| recall@5 symbols | 0.880 | 0.880 | 0.000 |
| impact_recall@5 | 0.931 | 0.931 | 0.000 |
| multi-project global | 0.500 | 0.500 | 0.000 |

Note: Phase 6 focus was breadth (new languages, new integrations) not retrieval tuning.
Synthetic eval baseline unchanged — no regressions introduced.

## What was built

### Cross-language parsers
- TypeScript/JavaScript parser via tree-sitter: functions, classes, arrow functions, imports
- Go parser: functions, structs, interfaces, imports
- Rust parser: functions, structs, enums, impl blocks, use declarations
- All four languages now produce symbols, relations, and importance scores on par with the Python parser

### Qdrant vector store integration
- `libs/embeddings/qdrant_store.py` — async Qdrant client wrapper
- `libs/embeddings/adapter.py` — `EmbeddingAdapter` protocol + `FakeEmbeddingAdapter` (deterministic, test-safe) + `OpenAIEmbeddingAdapter`
- Fixed collection set: `devctx_summaries`, `devctx_symbols`, `devctx_chunks`, `devctx_patterns`
- Isolation via payload (`project_id`, `language`, `entity_type`) — no per-project collections

### Obsidian vault sync
- `libs/obsidian/` — exports project summaries and symbol index to a configured Obsidian vault
- Incremental sync: only changed files regenerate their notes
- Front matter includes `project_id`, `language`, `importance`, `last_scanned`

### VS Code extension MVP
- Extension scaffolding with MCP client
- Commands: `lvdcp.pack` (navigate), `lvdcp.packEdit`, `lvdcp.status`
- Auto-invokes `lvdcp_pack` before opening multi-file searches in the editor

### Cross-project pattern detection
- `libs/patterns/` — detects recurring code patterns across registered projects
- Patterns stored in `devctx_patterns` Qdrant collection
- Surfaced in `lvdcp_status` and dashboard

### Test suite
- Phase 5 close: 457 tests
- Phase 6 close: 586 tests, 0 failures (588 collected, 1 deselected by marker)

## Known limitations
- precision@3 remains below 0.60 threshold — precision recovery is the primary Phase 7 target
- Large-project (1200+ files) multi-project recall at 0.200 — symbol and FTS coverage improvements needed
- VS Code extension is MVP-only: no inline decoration, no diff-aware edit packs yet
- Obsidian sync does not yet handle vault conflicts (manual resolution required)

## What to address in Phase 7
- Precision recovery: score cutoff tuning or a lightweight reranking pass
- Large-project multi-project recall: expand symbol coverage, improve FTS weighting
- VS Code extension: inline decorations, diff-aware packs, published to marketplace
- Obsidian conflict resolution strategy
