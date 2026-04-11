# Phase 3c.2 Stage 1 — Deterministic Retrieval Fixes

**Status:** Approved 2026-04-12
**Owner:** Vladimir Lukin
**Follows:** Phase 3c.1 complete (`phase-3c1-complete` tag + polish pass, version 0.3.3)
**Precedes:** Phase 3c.2 Stage 2 (vector + rerank) — **only triggered if Stage 1 fails eval gate**

## 1. Цель

Закрыть Phase 3c.2 eval gate (`recall@5 files ≥ 0.92` на synthetic fixture + `recall@5 files ≥ 0.80` на real-world LV_DCP queries) через три targeted deterministic fixes в `libs/retrieval/pipeline.py` — **без LLM retrieval, без vector search, без новых зависимостей**. Если Stage 1 hit'ает gate → tag `phase-3c2-complete`, Stage 2 не реализуется. Если fail'ит → тот же spec процесс открывается заново для Stage 2.

**Философия:** data-driven scope. Failure analysis (docs/eval/3c2-failure-analysis.md) показал что 11 из 15 документированных failures фиксятся дешёвыми детерминистическими изменениями — нет смысла строить LLM retrieval infrastructure для проблем, которые решаются multiplier'ами.

## 2. Context и измеренные failure patterns

Измерения от 2026-04-12 на текущем pipeline (после Phase 3c.1 polish, `0.3.3`):

**Synthetic fixture** (`tests/eval/queries.yaml` + `impact_queries.yaml`, 32 queries):
- recall@5 files: **0.891** (target 0.92)
- precision@3 files: 0.620
- recall@5 symbols: 0.833
- impact_recall@5: **0.819** (target 0.85)

**Real LV_DCP** (`tests/eval/real_queries.yaml`, 15 queries, new fixture from failure analysis):
- recall@5 files: **0.611** (massively below synthetic)
- 7/15 queries с recall < 1.0
- 5 of those 7 failures — **docs dominance** pattern

Три categories failures и projected fix impact:

| Category | Failures | Fix | Projected delta |
|---|---|---|---|
| Docs dominance (real only) | 5 real | Role-weighted fusion | real 0.611 → ~0.87 |
| Config file retrieval | 4 synthetic | Config boost heuristic | synthetic 0.891 → ~0.95 |
| Graph expansion depth weak | 3 synthetic + 1 real | Depth=3 в edit mode | synthetic +0.01, real +0.02 |

Combined projection (Stage 1 pass case):
- synthetic recall@5: **~0.95** (target 0.92, margin +0.03)
- real LV_DCP recall@5: **~0.87** (target 0.80, margin +0.07)
- impact_recall@5: **~0.87** (target 0.85, margin +0.02)

## 3. Scope — 5 deliverables

### D1 — Role-weighted score fusion

**Problem:** 5 real-world LV_DCP queries fail because `docs/superpowers/specs/*.md`, `docs/dogfood/*.md` rank in top-5 ahead of code files. FTS strongly matches concentrated project keywords in spec/plan documents; code files get diluted scores across many files.

**Fix:** apply role-based multiplier to final score for each candidate file, after graph expansion and before score decay cutoff. Multipliers per query mode:

| role | navigate mode | edit mode |
|---|---|---|
| `source` | ×1.0 | ×1.0 |
| `test` | ×0.85 | ×0.95 |
| `config` | ×1.10 | ×1.15 |
| `docs` | ×0.35 | ×0.40 |
| `other` | ×0.70 | ×0.70 |

**Docs override:** if query text contains any of `{docs, documentation, readme, changelog, architecture, design, spec, adr}` — docs role receives override multiplier ×1.20 instead of the penalty. This preserves the q14-architecture-doc synthetic case where the user explicitly asks for docs.

**Implementation:**

```python
# libs/retrieval/pipeline.py

ROLE_WEIGHTS_NAVIGATE: dict[str, float] = {
    "source": 1.0,
    "test": 0.85,
    "config": 1.10,
    "docs": 0.35,
    "other": 0.70,
}
ROLE_WEIGHTS_EDIT: dict[str, float] = {
    "source": 1.0,
    "test": 0.95,
    "config": 1.15,
    "docs": 0.40,
    "other": 0.70,
}
DOCS_OVERRIDE_KEYWORDS: frozenset[str] = frozenset({
    "docs", "documentation", "readme", "changelog",
    "architecture", "design", "spec", "adr",
})
DOCS_OVERRIDE_MULTIPLIER = 1.20


def _apply_role_weights(
    file_scores: dict[str, float],
    file_roles: dict[str, str],
    query: str,
    mode: str,
) -> None:
    weights = ROLE_WEIGHTS_EDIT if mode == "edit" else ROLE_WEIGHTS_NAVIGATE
    query_lower = query.lower()
    wants_docs = any(kw in query_lower for kw in DOCS_OVERRIDE_KEYWORDS)
    for path, score in list(file_scores.items()):
        role = file_roles.get(path, "other")
        if wants_docs and role == "docs":
            file_scores[path] = score * DOCS_OVERRIDE_MULTIPLIER
        else:
            file_scores[path] = score * weights.get(role, 0.70)
```

**Integration:** called from `RetrievalPipeline.retrieve()` after `_stage_graph` and before `_apply_score_decay`. Requires passing a `file_roles: dict[str, str]` map to pipeline — loaded lazily once at pipeline construction from `cache.iter_files()`.

```python
# libs/retrieval/pipeline.py — RetrievalPipeline.__init__
def __init__(self, *, cache, fts, symbols, graph=None):
    # existing init...
    self._file_roles: dict[str, str] | None = None

def _get_file_roles(self) -> dict[str, str]:
    if self._file_roles is None:
        self._file_roles = {f.path: f.role for f in self._cache.iter_files()}
    return self._file_roles
```

### D2 — Config file boost heuristic

**Problem:** 4 synthetic queries (`q16`, `i04`, `i05`, `i06`) expect `config/settings.yaml` but it doesn't reach top-5 — config files have sparse FTS content and no graph neighborhood.

**Fix:** when query text contains config-ish keywords, inject all `role="config"` files into the candidate set with a baseline score, then let normal ranking + role weights take over.

```python
# libs/retrieval/pipeline.py

CONFIG_TRIGGER_KEYWORDS: frozenset[str] = frozenset({
    "config", "settings", "timeout", "ttl", "schedule",
    "env", "port", "url", "host", "secret", "credential",
    "database", "db", "connection",
})
CONFIG_BOOST_BASELINE = 0.5


def _maybe_boost_config_files(
    query: str,
    file_scores: dict[str, float],
    file_roles: dict[str, str],
) -> None:
    query_lower = query.lower()
    if not any(kw in query_lower for kw in CONFIG_TRIGGER_KEYWORDS):
        return
    for path, role in file_roles.items():
        if role == "config":
            current = file_scores.get(path, 0.0)
            file_scores[path] = max(current, CONFIG_BOOST_BASELINE)
```

**Edge case:** single-word queries like `"timeout"` will boost all config files. Baseline `0.5` is deliberately low — any real code file with the keyword will outrank. The boost only guarantees config appears in the candidate pool at all, not that it wins top rank.

### D3 — Graph expansion depth tuning for edit mode

**Problem:** synthetic impact queries `i01-session-storage-change` (expected `app/workers/cleanup.py`) and `i06-db-connection-migration` (expected `app/main.py`) fail because expected files are 3 graph hops from seed files. Current `GRAPH_EXPANSION_DEPTH=2` cannot reach.

**Fix:** raise depth to 3 **only for edit mode**. Navigate mode stays at 2 to preserve precision on "where is X" queries.

```python
# libs/retrieval/pipeline.py

GRAPH_EXPANSION_DEPTH = 2        # navigate mode (existing default)
GRAPH_EXPANSION_DEPTH_EDIT = 3   # edit mode, new


# In Pipeline._stage_graph:
def _stage_graph(self, graph, file_scores, mode):
    depth = GRAPH_EXPANSION_DEPTH_EDIT if mode == "edit" else GRAPH_EXPANSION_DEPTH
    # ... existing call to expand_via_graph with `depth=depth`
```

**Risk mitigation:** decay factor `0.7^3 = 0.343` at depth 3 already attenuates scores. Combined with role weights, third-hop candidates only surface if they have strong own-signal (FTS match or role boost).

### D4 — Extended eval harness per-query report

**Problem:** eval debugging currently requires hand-written Python scripts to extract per-query ranks and misses. This has been done twice (original 3c.1 brainstorm + Phase 3c.2 failure analysis). Automate.

**Fix:** add `generate_per_query_report(report: EvalReport) -> str` to `tests/eval/run_eval.py` returning Markdown. Add shell wrapper `scripts/eval-report.sh` that runs eval and writes timestamped report to `docs/eval/YYYY-MM-DD-<tag>.md`.

Report format:

```markdown
# Eval Report — 2026-04-12 14:30 — baseline

## Summary
- recall@5 files:    0.891 (target 0.92)
- precision@3 files: 0.620 (target 0.60)
- recall@5 symbols:  0.833
- impact_recall@5:   0.819 (target 0.85)

## Per-query breakdown

| id | mode | exp_n | recall@5 | rank_of_first_expected | missed |
|---|---|---|---|---|---|
| q01-user-model | navigate | 1 | 1.00 | 2 | — |
| q04-refresh-flow | navigate | 2 | 0.50 | 1 | app/handlers/auth.py |
| i04-access-ttl-reduction | edit | 2 | 0.50 | 1 | config/settings.yaml |
...
```

Shell wrapper:

```bash
#!/usr/bin/env bash
# scripts/eval-report.sh <tag>
set -eu
tag="${1:-baseline}"
date_str=$(date +%Y-%m-%d)
output="docs/eval/${date_str}-${tag}.md"
uv run python -c "
from pathlib import Path
from tests.eval.run_eval import run_eval, generate_per_query_report
from tests.eval.retrieval_adapter import retrieve_for_eval
report = run_eval(retrieve_for_eval)
md = generate_per_query_report(report)
Path('${output}').parent.mkdir(parents=True, exist_ok=True)
Path('${output}').write_text(md)
print(f'wrote {output}')
"
```

### D5 — Eval gate + dogfood

Stage 1 closes when **all 5** eval gates pass:

1. `recall@5 files` on synthetic ≥ **0.92**
2. `recall@5 files` on real LV_DCP ≥ **0.80**
3. `precision@3 files` on synthetic ≥ 0.60 (no regression)
4. `impact_recall@5` on synthetic ≥ **0.85**
5. `recall@5 symbols` on both fixtures ≥ 0.80 (no regression)

Plus sanity:
- `make lint typecheck test` green, new tests all pass
- Dogfood: 5 real queries (r03, r04, r05, r12, r13) show code files in top-5 after fix — manual verification captured in `docs/dogfood/phase-3c2.md`

**If all pass:** `pyproject.toml` version `0.3.3 → 0.3.4`, git tag `phase-3c2-complete`, Stage 2 not triggered, Phase 3 closed.

**If any fails:** Stage 1 does NOT merge to main. Write `docs/eval/stage1-shortfall.md` with per-query breakdown of failing eval metrics, brainstorm Stage 2 (vector + rerank on summaries).

## 4. Architecture

```
RetrievalPipeline.retrieve(query, mode):
  │
  ├─ _stage_symbol_match       (existing, unchanged)
  ├─ _stage_fts_search          (existing, unchanged)
  │
  ├─ _stage_graph (modified)
  │   └─ depth = 3 if mode=="edit" else 2   [D3]
  │
  ├─ _maybe_boost_config_files(query, file_scores, roles)   [D2, NEW]
  │   └─ adds config files to candidate pool if query matches triggers
  │
  ├─ _apply_role_weights(file_scores, roles, query, mode)   [D1, NEW]
  │   └─ multiplies each score by role-specific weight
  │
  ├─ _apply_score_decay        (existing)
  └─ final ranking + trace
```

All three new passes operate on `file_scores: dict[str, float]` — pure functions, no I/O, no new dependencies, no async work. Zero new modules. The only state addition is a `_file_roles` cache on the pipeline instance, populated lazily on first `retrieve()` call.

## 5. Files

### Modified

- `libs/retrieval/pipeline.py` — four constants (ROLE_WEIGHTS_*, DOCS_OVERRIDE_*, CONFIG_TRIGGER_KEYWORDS, GRAPH_EXPANSION_DEPTH_EDIT), two new methods (`_apply_role_weights`, `_maybe_boost_config_files`), one new lazy loader (`_get_file_roles`), call-order change in `retrieve()`
- `tests/eval/run_eval.py` — `generate_per_query_report(report) -> str` function
- `pyproject.toml` — version bump `0.3.3` → `0.3.4` (only if Stage 1 passes)

### New

- `scripts/eval-report.sh` — shell wrapper around run_eval + per-query report
- `docs/eval/2026-04-12-baseline.md` — pre-change snapshot (Stage 1 step 1)
- `docs/eval/2026-04-12-stage1-after.md` — post-change snapshot (Stage 1 final)
- `docs/dogfood/phase-3c2.md` — dogfood report with before/after for r03, r04, r05, r12, r13
- `tests/unit/retrieval/test_pipeline_role_weights.py` — unit tests for D1 + D2 + D3

### NOT touched

- `libs/llm/*` — Phase 3c.1 LLM infrastructure untouched. Stage 1 doesn't use LLM retrieval.
- `libs/summaries/*` — Phase 3c.1 summaries store untouched. Summaries remain in dashboard, unused for retrieval ranking.
- `libs/vector/*` — does not exist in Stage 1 scope. Stage 2 only.
- `libs/retrieval/graph_expansion.py`, `fts.py`, `index.py`, `coverage.py`, `trace.py` — retrieval algorithm primitives untouched. Only pipeline orchestration gets new passes.
- `apps/mcp/*`, `apps/ui/*`, `apps/cli/*` — no user-facing surface changes.

## 6. Testing

### Unit tests (new)

`tests/unit/retrieval/test_pipeline_role_weights.py`:

- `test_role_weights_demote_docs_in_navigate_mode` — scenario: two files with equal FTS score, one code one docs, query is "how does X work". Code should rank first.
- `test_role_weights_boost_config_on_config_query` — scenario: query "what is the ttl", config file has lower FTS score than code. After boost, config file enters top-5.
- `test_docs_override_when_query_wants_docs` — query "architecture documentation", docs file ranked first despite 0.35 base penalty.
- `test_edit_mode_deeper_graph_walk` — synthetic graph with target at depth 3. Navigate mode misses (depth 2), edit mode finds (depth 3).
- `test_file_roles_lazy_loaded_once` — verify `_file_roles` cached on first retrieve, not re-loaded on subsequent calls.
- `test_config_trigger_keywords_case_insensitive` — query "TIMEOUT" should boost config files same as "timeout".

### Integration tests (new)

`tests/integration/test_real_query_not_dominated_by_docs.py`:
- Build a tiny repo with 1 code file and 3 docs files all containing keyword "widget". Query "widget rendering". Assert code file is in top-3. Regression test for r04-like failures.

### Eval gate (updated)

`tests/eval/test_eval_harness.py::test_eval_harness_meets_thresholds` — existing test. Will start hitting 0.95+ after D1+D2+D3 land. Update `thresholds.yaml` if needed to reflect new Stage 1 expected values.

### Manual dogfood

`scripts/eval-report.sh baseline` → capture current state
... implement D1+D2+D3 ...
`scripts/eval-report.sh stage1-after` → capture new state

Diff the two reports, paste into `docs/dogfood/phase-3c2.md`.

Run `ctx pack` manually on 5 real LV_DCP queries (r03, r04, r05, r12, r13) via MCP from Claude Code, check top-5 has expected code files, record outputs in dogfood report.

## 7. Exit criteria

1. All 5 eval gates pass (see §3 D5).
2. New unit tests pass, zero regressions in existing test suite.
3. `make lint typecheck test` clean.
4. `pyproject.toml` bumped `0.3.3 → 0.3.4`.
5. Dogfood report `docs/dogfood/phase-3c2.md` captures before/after for 5 real queries.
6. `docs/eval/2026-04-12-baseline.md` and `docs/eval/2026-04-12-stage1-after.md` committed.
7. Git tag `phase-3c2-complete` on HEAD main.
8. README optionally updated with a short note about retrieval improvements in 0.3.4.
9. `tests/eval/real_queries.yaml` checked into the suite as part of ongoing regression surface.

## 8. Non-goals

Stage 1 does NOT do:

- Vector search, embeddings, sqlite-vec integration — Stage 2 only
- LLM-based rerank, listwise reranker, cross-encoder — Stage 2 only
- Query expansion, paraphrase generation — Phase 5+
- Learned-to-rank models — never
- Cross-language parsers (TypeScript, Go, Rust) — Phase 5
- Per-project retrieval configuration via UI — no UI changes
- Summary-based retrieval (using 3c.1's cached summaries as ranking signal) — Stage 2 only
- Cost tracking changes — Stage 1 makes zero API calls
- Backwards compatibility for old retrieval ranking behavior — this is intentional behavior change; role weights activate by default
- LLM prompt engineering — not relevant to Stage 1
- Custom role configurations via `llm.retrieval_role_weights` in config.yaml — YAGNI, hardcode defaults

## 9. Risks

**R1 — Role weights are theory-calibrated, may mis-tune on live data.**
Mitigation: D4 per-query report runs before and after changes, showing exactly which queries changed rank. Iterate on multipliers (max 2-3 attempts) based on measured deltas, not intuition. If after 3 iterations synthetic or real fails to hit targets → declare Stage 1 insufficient, open Stage 2.

**R2 — Config boost introduces noise on config-word queries that are actually about code.**
Example: query `"timeout handling in retries"` is about the retry code, not config. Baseline score of 0.5 is deliberately low — real code with keyword score outranks. Verify via D4 report on synthetic fixture queries that contain `timeout`, `schedule`, etc.

**R3 — Graph depth=3 in edit mode balloons candidate count, hurts precision.**
Mitigation: decay `0.7^3 = 0.343` already attenuates 3-hop candidates by 2/3. If precision@3 drops below 0.60 gate, revert D3 to depth=2 everywhere and accept lower impact_recall coverage (fall back to Stage 2 for i01, i06).

**R4 — Real query fixture is small (15 queries) and I authored it myself, may not represent actual user failures.**
Mitigation: real_queries.yaml is a starting baseline, not the definitive benchmark. Phase 4+ can expand it. For now, 15 queries + 32 synthetic = 47 total — small but high-signal on the specific failure patterns we're fixing.

**R5 — Docs override (`wants_docs=True`) might leak into code queries that happen to contain keyword like "design" or "architecture".**
Example: `"design of the retrieval pipeline"` — user wants code, keyword `design` triggers override, docs boosted. Mitigation: override only applies multiplication ×1.2 (not reset), so strongest signal still wins; and DOCS_OVERRIDE_KEYWORDS list is short/unambiguous. Add test `test_design_in_code_query_still_returns_code` to guard.

**R6 — Stage 1 passes synthetic but fails real LV_DCP target 0.80.**
Recoverable: real queries missing = open Stage 2 spec for just those. Stage 1 can still tag if synthetic passes — we're measuring both fixtures for different reasons (synthetic = eval baseline, real = production proxy).

**R7 — Stage 2 fallback increases total Phase 3c.2 time from ~3 days to ~3 days + 2-3 weeks.**
Accepted risk. Variant C was chosen consciously by user on 2026-04-12 as "hedge approach". If Stage 1 fails gate, we get data on exactly which queries still need LLM retrieval — targeted, not spec-driven.

## 10. Estimate

| Task | Days |
|---|---|
| D1 role-weighted fusion + unit tests | 1.0 |
| D2 config boost heuristic + unit tests | 0.5 |
| D3 graph depth tuning + unit tests | 0.3 |
| D4 eval harness extension + per-query report + shell wrapper | 0.5 |
| D5 eval run + dogfood + phase-3c2.md writeup | 0.5 |
| Calibration iterations (0-2 passes based on data) | 0.3 (max 0.5) |
| Final quality gate (lint/typecheck/test/merge/tag) | 0.2 |
| **Total** | **~3.3 working days** |

## 11. Versioning

- `pyproject.toml`: `0.3.3` → `0.3.4`
- Git tag: `phase-3c2-complete` on HEAD main (if Stage 1 passes gate)
- If Stage 2 later triggered: it gets its own version bump (0.3.5) and same tag `phase-3c2-complete` moves forward OR stays pinned at Stage 1 close with new tag `phase-3c2-stage2-complete`. Defer this naming decision until Stage 2 is actually needed.

## 12. Stage 2 pre-scope (if triggered)

**Not in this spec**, but documented for continuity:

If Stage 1 fails any of the 5 eval gates, Stage 2 brainstorm reopens with concrete target queries (the ones Stage 1 couldn't fix). Stage 2 scope will be:

- Vector embeddings of file summaries (already cached from Phase 3c.1 in `~/.lvdcp/summaries.db`) via BGE-M3 local or OpenAI `text-embedding-3-small`
- sqlite-vec store at `.context/vectors.db` per project
- Vector stage added to retrieval pipeline between graph expansion and role weighting
- Listwise LLM rerank via `LLMClient.rerank` (Phase 3c.1 stub becomes functional)
- Fusion strategy: vector score weight calibrated against FTS + graph weights from Stage 1
- Eval gate: same 5 thresholds, now must be hit

**Estimated Stage 2 budget if triggered:** 2-3 weeks, new `libs/vector/` package, `libs/retrieval/rerank.py`, extensions to `libs/retrieval/pipeline.py`.

## 13. Approval log

- 2026-04-12 — brainstorm session with Vladimir Lukin. Design points closed:
  - Option C (deterministic first, LLM retrieval only if Stage 1 fails): approved
  - Role weight values (navigate + edit tables): approved
  - Config trigger keywords list: approved
  - Graph depth=3 for edit mode only: approved
  - Eval gate thresholds (0.92 synthetic + 0.80 real): approved
  - Full Stage 1 design preview: approved
