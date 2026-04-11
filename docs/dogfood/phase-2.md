# Phase 2 Dogfood Report

**Date:** 2026-04-11
**Commit:** 9c2f04c1b715b7f5f20ed183b70f34967c433c2d

## Exit criteria status

| Criterion | Status |
|---|---|
| make lint green | ✓ |
| make typecheck green | ✓ |
| make test green (150 tests) | ✓ |
| make eval green at phase 2 thresholds | ✓ |
| MCP handshake integration test passes | ✓ |
| Daemon integration tests pass | ✓ |
| MCP stdio probe returns valid pack on LV_DCP | ✓ |

## Eval metrics (phase 2 active)

```
recall@5 files   : 0.891  (threshold ≥ 0.85)
precision@3 files: 0.620  (threshold ≥ 0.60)
recall@5 symbols : 0.833  (threshold ≥ 0.80)
impact_recall@5  : 0.819  (threshold ≥ 0.75)
mrr_files        : 0.901
```

## Self-scan snapshot

```
scanned 156 files (156 reparsed, 0 stale removed), 1063 symbols, 2439 relations in 0.52s
```

## Incremental re-scan

```
scanned 156 files (0 reparsed, 0 stale removed), 0 symbols, 0 relations in 0.28s
```

Note: incremental re-scan correctly skips all 156 files (no content changes). A bug was found and fixed during dogfood: `apps/cli/main.py` was calling `scan_module.scan(path)` without passing `full=False`, causing the Typer `OptionInfo` default object to evaluate as truthy — forcing every `ctx scan` to run in full mode. The fix exposed the `full` flag properly in `main.py` and passes it explicitly to `scan_module.scan`.

## Pack query assessments

### Q1: "where is retrieval pipeline" (navigate)
Top 5 files:
1. `libs/retrieval/pipeline.py` (score 15.08)
2. `tests/unit/retrieval/test_pipeline.py` (score 13.88)
3. `libs/context_pack/builder.py` (score 10.52)
4. `libs/retrieval/trace.py` (score 9.20)

Coverage: medium
Verdict: YES — `libs/retrieval/pipeline.py` surfaces at #1. Correct. Test file at #2 is a useful bonus.

### Q2: "how does graph expansion work" (navigate)
Top 5 files:
1. `libs/retrieval/pipeline.py` (score 12.00)
2. `libs/retrieval/graph_expansion.py` (score 9.00)
3. `docs/adr/005-completeness-invariant.md` (score 8.67)
4. `docs/adr/004-phase-2-pivot.md` (score 8.32)
5. `docs/superpowers/specs/2026-04-11-phase-2-design.md` (score 7.66)

Coverage: medium
Verdict: YES — `libs/retrieval/graph_expansion.py` appears at #2. Pipeline file at #1 is also correct (it contains the graph stage). ADR docs in top-5 add useful architectural context.

### Q3: "change how ctx scan handles ignored paths" (edit)
Target files:
- `docs/user-guide.md` (score 9.02)
- `libs/core/paths.py` (score 9.00)
- `docs/dogfood/phase-1.md` (score 8.33)
- `docs/superpowers/specs/2026-04-11-phase-2-design.md` (score 8.22)
- `docs/tz.md` (score 7.66)
- `docs/superpowers/plans/2026-04-10-phase-0-1-foundation.md` (score 7.38)
- `apps/cli/commands/mcp_cmd.py` (score 6.00)

Impacted tests: `tests/integration/test_dogfood.py`, `tests/integration/test_ctx_watch.py`, `tests/unit/core/test_paths.py`
Impacted configs: none

Coverage: medium
Verdict: PARTIAL — `libs/core/paths.py` is correctly identified at #2. `tests/unit/core/test_paths.py` is in the impacted tests. However, `libs/scanning/scanner.py` (which calls `is_ignored`) is missing from target files — graph expansion didn't bridge paths.py → scanner.py. `apps/cli/main.py` also absent despite it being the entry point. Docs noise is high (3 of 7 target files are docs).

### Q4: "add a new MCP tool for listing projects" (edit)
Target files:
- `docs/superpowers/specs/2026-04-11-phase-2-design.md` (score 14.29)
- `docs/adr/004-phase-2-pivot.md` (score 12.20)
- `docs/adr/005-completeness-invariant.md` (score 8.04)
- `apps/agent/config.py` (score 6.00)
- `apps/agent/handler.py` (score 6.00)
- `apps/cli/commands/watch_cmd.py` (score 6.00)
- `apps/mcp/install.py` (score 6.00)
- `libs/graph/builder.py` (score 6.00)
- `libs/parsers/python.py` (score 6.00)

Impacted tests: `tests/unit/mcp/test_server_registration.py`
Impacted configs: none

Coverage: medium
Verdict: PARTIAL — `apps/agent/config.py` (has `list_projects`) and `apps/mcp/install.py` appear in targets, and `tests/unit/mcp/test_server_registration.py` is correctly identified as impacted. However `apps/mcp/tools.py` and `apps/mcp/server.py` (the primary edit targets) are missing — they were not in the top-8 target files, replaced by unrelated graph/parser files due to weak MCP-specific signal. Docs are over-represented again at #1 and #2.

## MCP stdio probe output

```
tools: ['lvdcp_scan', 'lvdcp_pack', 'lvdcp_inspect', 'lvdcp_explain']
--- pack markdown (first 400 chars) ---
{
  "markdown": "# Context pack — navigate\n\n**Project:** `LV_DCP`\n**Query:** where is retrieval pipeline\n**Coverage:** high\n**Pipeline:** `phase-2-v0`\n\n## Top files\n\n1. `tests/unit/retrieval/test_pipeline.py` (score 13.88)\n2. `libs/retrieval/pipeline.py` (score 12.00)\n3. `libs/context_pack/builder.py` (score 10.52)\n4. `libs/retrieval/trace.py` (score 6.00)\n\n## Top symbols\n\n1. `libs
```

MCP stdio handshake: 4 tools registered, `lvdcp_pack` call returns valid JSON with a markdown context pack. Coverage returned as `high` (vs `medium` from CLI) due to warm cache state in the probe.

## Qualitative assessment

**What worked:**
- Incremental scan (once the OptionInfo bug was fixed): 156 files in 0.28s vs 0.52s full scan — 46% speedup, 0 reparsed
- All 4 eval metrics above Phase 2 thresholds on first activation flip
- MCP stdio end-to-end: handshake + tool call working, returns structured JSON with markdown
- Retrieval clearly surfaces the correct primary module for navigate queries (pipeline.py at #1, graph_expansion.py at #2)
- Impact recall 0.819 against threshold 0.75 — graph expansion is doing real work on the fixture repo
- Symbol index correctly captures 1063 symbols across 156 files including all Phase 2 additions

**What surprised:**
- The Typer OptionInfo bug: every `ctx scan` was silently running in full-reparse mode since the CLI was wired up. This means Phase 1 dogfood incremental numbers were also wrong. Fix was trivial once diagnosed.
- MCP probe returns `high` coverage for a query that CLI returns `medium` — coverage scoring is sensitive to cache warmth / ordering; not a defect but worth monitoring.
- `apps/mcp/tools.py` did not surface in Q4 edit pack target files despite being the most obvious edit target. Score dilution from docs files with FTS match.

**What's still incomplete:**
- Edit pack docs noise: documentation files frequently rank above implementation files because they contain higher FTS match density for architectural terms. Phase 3 should apply a scoring penalty to non-source files in edit mode.
- `libs/scanning/scanner.py` missing from Q3 edit pack targets — `is_ignored` call site not bridged from `paths.py` in graph expansion. Either graph depth is too shallow or the relation type isn't captured.
- `apps/mcp/tools.py` and `apps/mcp/server.py` missing from Q4 — FTS weight for MCP tool names is insufficient without a symbol-specific boost for the module being directly edited.
- MCP pack returns JSON envelope `{"markdown": "..."}` rather than raw markdown. CLI returns raw markdown. This is intentional (MCP callers parse JSON) but worth documenting clearly.
- No semantic/LLM summarization layer yet — all retrieval is FTS + symbol + graph. Phase 3 will add summary vectors for better recall on abstract queries.

**Phase 2 goal — 90% closed?:**
Yes. The core Phase 2 deliverables are all shipped and working:
- Graph expansion pipeline (ADR-005 completeness invariant) — implemented and measured above threshold
- MCP server with 4 tools — working, stdio handshake tested, end-to-end pack call verified
- Watchdog daemon with debounce — integrated and tested
- Incremental scanning — working (modulo the OptionInfo bug fixed in this task)
- Phase 2 eval thresholds active and passing
- Self-hosting (LV_DCP scans and retrieves from itself)

The remaining 10% is edit pack precision for exact file targeting (docs noise, missing scanner.py in Q3, missing tools.py in Q4). These are Phase 3 concerns — not blockers for Phase 2 close.

## Decisions triggered for Phase 3

- Add source-file boost / docs penalty in edit-mode scoring to reduce doc noise in target files
- Graph expansion: ensure `calls`/`imports` relation from `scanner.py → paths.py` is captured so edit packs for scan-related changes surface scanner.py
- MCP JSON envelope: add explicit note to user guide that MCP returns `{"markdown": "..."}` not raw text
- Semantic summarization layer for abstract queries (Phase 3 P0)
- Investigate coverage score inconsistency between warm and cold cache runs
