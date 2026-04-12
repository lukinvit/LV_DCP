# Phase 3c.1 Dogfood Report

**Date:** 2026-04-11 (gate completed 2026-04-12)
**Tag:** phase-3c1-complete
**Version:** 0.3.2
**Author:** Vladimir Lukin

## Exit criterion verification

Script: [scripts/phase-3c1-dogfood.sh](../../scripts/phase-3c1-dogfood.sh)
Full log: `/tmp/phase-3c1-dogfood.log`
Provider: OpenAI (default), model `gpt-4o-mini`, prompt v1.

### ctx summarize cost per project (first cold run)

| Project | Files | New summaries | Cached | Cost USD | Tokens in→out | Latency | Failed |
|---|---|---|---|---|---|---|---|
| LV_DCP | 253 | 227 | 24 | $0.0632 | 336806 → 21072 | 56.86s | 2 |
| Project_Medium_A | 146 | 107 | 15 | $0.0227 | 112705 → 9721 | 28.87s | 24 |
| Project_Medium_B | 109 | 71 | 18 | $0.0131 | 61766 → 6463 | 21.54s | 20 |
| **Total** | **508** | **405** | **57** | **$0.099** | **511K → 37K** | **107s** | **46** |

**ADR-001 budget compliance:** `$0.099 ≪ $0.50` canary budget — **×5 margin**. LV_DCP alone at `$0.0632` is within target. 

The "cached" column on first run reflects content hash collisions across projects (e.g. empty `__init__.py`, common boilerplate) — the cache is global keyed on `(content_hash, prompt_version, model)` so duplicate content is reused immediately.

### Cache hit rate on second run

Re-ran `ctx summarize` on LV_DCP only:

```
summarized 2 new files (251 cached), cost $0.0053, 34096→227 tokens, in 7.11s
```

**99.2% cache hit rate (251 / 253).** The 2 "new" files were the ones that failed on the cold run (rate-limited / one JSON parse error) and got retried on warm run. Cost for retry: $0.0053. A truly unchanged third run would be 253/253, $0.0000.

### ctx mcp doctor output

```
✓ claude CLI             PASS  found on PATH
✓ claude mcp list        PASS  lvdcp registered
✓ mcp handshake          PASS  initialize round-trip < 3s
✓ config.yaml            PASS  1 project(s) registered
✓ project caches         PASS  1/1 accessible
⚠ CLAUDE.md managed      WARN  version mismatch: 0.0.0 → 0.3.2
    hint: re-run `ctx mcp install` to refresh
✓ legacy pollution       PASS  clean
✓ LLM provider           PASS  openai/gpt-4o-mini
✓ LLM budget             PASS  $0.10 / $25

Result: 8 PASS, 1 WARN, 0 FAIL
```

**9 checks confirmed** (was 7 at Phase 3b). New checks 8 (LLM provider) and 9 (LLM budget) both PASS.

The WARN on check 6 is the **upgrade self-heal signal working as designed**: installed `CLAUDE.md` managed section tag is `0.0.0` (never re-run after version bump), new `libs/core/version.py::LVDCP_VERSION` is `0.3.2`. Running `ctx mcp install` refreshes the managed section → WARN becomes PASS. Exit criterion 14 upgrade path verified.

### Sample summaries (manual quality check)

5 random summaries from LV_DCP (model `gpt-4o-mini`):

1. **`libs/retrieval/pipeline.py`**:
   > This file implements a multi-stage deterministic retrieval pipeline that processes queries through various stages, including symbol matching, full-text search, graph expansion, and final ranking with score decay. The key exported symbol is the `RetrievalPipeline` class, which provides the `retrieve` method to execute the retrieval process and return a `RetrievalResult` containing files, symbols, scores, and a trace for explainability. This pipeline likely serves as a component in a larger system focused on efficient information retrieval from a codebase or document repository, enhancing search capabilities through structured stages.

2. **`libs/claude_usage/reader.py`**:
   > This file is responsible for parsing JSONL session files located in the user's Claude project directory and yielding `UsageEvent` rows for records of type "assistant." The key exported function is `read_session_file`, which reads a specified session file and yields `UsageEvent` instances while handling malformed lines and allowing for incremental reads via a byte offset. It likely serves as a component in a larger system that analyzes or processes usage data from Claude sessions.

3. **`apps/ui/routes/index.py`**:
   > This file defines a FastAPI route that serves as the main index view for a multi-project application, responding to GET requests at the root URL. Key exported symbols include the `index` function, which processes the request, builds workspace status, loads configuration, computes budget status, and renders an HTML template with the gathered data. It plays a role in a larger system by providing a centralized view of project statuses and budget information, likely for a dashboard or management interface.

4. **`libs/mcp_ops/doctor.py`**:
   > The file implements a series of health checks for the MCP (Managed Code Platform) environment, ensuring that various components such as the CLI, configuration files, and LLM (Large Language Model) provider are correctly set up and functioning. Key exported functions include `run_doctor`, which executes the checks and returns a `DoctorReport`, and rendering functions like `render_table` and `render_json` for displaying the results. This module plays a critical role in maintaining the integrity and operational readiness of the MCP system by providing diagnostics and actionable insights.

5. **`libs/llm/cost.py`**:
   > This file is responsible for defining static pricing tables and calculating costs associated with various supported LLM (Large Language Model) models. The key exported function is `calculate_cost`, which computes the USD cost for a single LLM call based on input and output tokens, while raising an error if the specified model is not recognized. It plays a role in a larger system by providing cost estimation functionality for LLM usage, which can be critical for budgeting and resource allocation in applications utilizing these models.

**Quality assessment:** technically accurate, correct identification of exported symbols, appropriate technical tone. **One hallucination** — "MCP (Managed Code Platform)" in summary #4 should be "Model Context Protocol". Minor, not a blocker. Can be fixed in prompt v2 by adding a glossary hint ("MCP = Model Context Protocol" in system message). Noted in Known issues.

## Changed surface

- **`libs/llm/`** — new pluggable provider package: `base.py` (Protocol + DTOs), `models.py` (pydantic), `errors.py` (LLMConfigError/LLMProviderError/BudgetExceededError), `cost.py` (pricing table for 8 models), `openai_client.py`, `anthropic_client.py`, `ollama_client.py`, `registry.py` (factory).
- **`libs/summaries/`** — new package: `store.py` (sqlite cache keyed on content+prompt+model, `~/.lvdcp/summaries.db`), `prompts.py` (FILE_SUMMARY_PROMPT_V1), `generator.py` (thin wrapper), `pipeline.py` (orchestrator with asyncio Semaphore + per-file error isolation).
- **`libs/status/budget.py`** — new: `compute_budget_status(LLMConfig) -> BudgetInfo`, 7d/30d rolling sums from summaries.db.
- **`libs/status/models.py`** — extended with `BudgetInfo` DTO.
- **`libs/status/aggregator.py`** — `_resolve_config_path` → public `resolve_config_path`.
- **`libs/core/projects_config.py`** — extended with `LLMConfig` pydantic + `DaemonConfig.llm: LLMConfig = Field(default_factory=LLMConfig)` (backwards-compat default).
- **`libs/mcp_ops/doctor.py`** — 2 new checks (`check_llm_provider`, `check_llm_budget`), total 9 checks.
- **`apps/mcp/tools.py`** — `StatusResponse` gains `budget: BudgetInfo | None` field; `lvdcp_status` populates it.
- **`apps/cli/commands/summarize.py`** — new `ctx summarize <path>` Typer command with rich progress bar.
- **`apps/cli/main.py`** — wired `summarize` command.
- **`apps/ui/routes/settings.py`** — new `/settings` GET/POST + `/api/settings/test-connection`.
- **`apps/ui/templates/settings.html.j2`** — settings form template.
- **`apps/ui/templates/partials/budget_widget.html.j2`** — topbar widget.
- **`apps/ui/templates/partials/usage_widget.html.j2`** — wrapped in `{% if ws_usage_7d %}` guard.
- **`apps/ui/templates/base.html.j2`** — added Settings nav link + budget widget include.
- **`apps/ui/routes/index.py`** + **`project.py`** — inject `budget` into template context.
- **`apps/ui/static/css/base.css`** — `.budget-widget`, `.settings-form`, `.env-var-status` styles.
- **`apps/ui/main.py`** — registered settings router.
- **`pyproject.toml`** — new deps: `openai>=1.50`, `anthropic>=0.40`, `tiktoken>=0.7`; version `0.3.1` → `0.3.2`.
- **`docs/adr/006-llm-provider-abstraction.md`** — new ADR documenting the pluggable design rationale.
- **`README.md`** — Phase 3c.1 section with usage + provider setup.
- **`scripts/phase-3c1-dogfood.sh`** + **`docs/dogfood/phase-3c1.md`** — dogfood harness.

## Eval metrics (must stay identical — retrieval untouched)

| Metric | Threshold | Phase 3b close | Phase 3c.1 close | Result |
|---|---|---|---|---|
| recall@5 files | ≥ 0.85 | 0.891 | **0.891** | same |
| precision@3 files | ≥ 0.60 | 0.620 | **0.620** | same |
| recall@5 symbols | ≥ 0.80 | 0.833 | **0.833** | same |
| impact_recall@5 | ≥ 0.75 | 0.819 | **0.819** | same |

**Zero retrieval regression.** Identical numbers confirm retrieval pipeline was untouched in 3c.1 as the spec required.

## Test suite

- Phase 3b close: 278 passed
- Phase 3c.1 close: **335 passed, 1 deselected** (+57 new tests, +20%)
- `make lint typecheck test` clean: ruff all checks passed, mypy strict 0 issues in 93 source files, ruff format clean (after one `chore(phase-3c1): ruff format pass` commit).
- Breakdown of new test categories:
  - `tests/unit/core/test_projects_config_llm.py` — 4 tests (LLMConfig defaults, backwards compat, explicit config)
  - `tests/unit/llm/test_cost.py` — 7 tests (pricing table + calculate_cost)
  - `tests/unit/llm/test_openai_client.py` — 5 tests (mocked SDK)
  - `tests/unit/llm/test_anthropic_client.py` — 5 tests
  - `tests/unit/llm/test_ollama_client.py` — 4 tests
  - `tests/unit/llm/test_registry.py` — 6 tests
  - `tests/unit/summaries/test_store.py` — 5 tests
  - `tests/unit/summaries/test_generator.py` — 1 test
  - `tests/unit/summaries/test_pipeline.py` — 3 tests
  - `tests/unit/status/test_budget.py` — 4 tests
  - `tests/unit/mcp_ops/test_doctor.py` — 4 tests added (check_llm_provider + check_llm_budget)
  - `tests/integration/test_lvdcp_status_budget.py` — 3 tests
  - `tests/integration/test_ctx_summarize.py` — 2 tests
  - `tests/integration/test_ui_settings.py` — 4 tests

## Upgrade smoke test

From `phase-3b-complete` state, the upgrade flow was verified in-place during dogfood:

- **Initial state** (phase-3b-complete): CLAUDE.md managed section contains `<!-- lvdcp-managed-version: 0.0.0 -->`
- **After pull + `uv sync --all-extras`**: new code active, but managed section still at 0.0.0
- **`ctx mcp doctor`** → check 6 WARN: "version mismatch: 0.0.0 → 0.3.2, re-run `ctx mcp install`" — **self-heal signal fired as designed**
- **`ctx mcp install`** refreshes managed section → next doctor run shows 9/9 PASS (once OPENAI_API_KEY is exported)

Upgrade path verified end-to-end. No manual config edits required.

## Known issues

- **Rate limiting during cold scan on small OpenAI tiers.** Default concurrency=10 + 400K tokens/minute throughput saturates tier-1 (200K TPM) around the 150th file in a batch. 46 files failed with HTTP 429 across the 3 dogfood projects (mostly on Project_Medium_A and Project_Medium_B). The failed files get retried successfully on the next run (cache miss + fresh TPM bucket). **Mitigation for Phase 5+**: add exponential backoff with more aggressive jitter; drop default concurrency from 10 to 4 for tier-1 users. **Workaround now**: `ctx summarize <path> --concurrency 3` or re-run after first failure to pick up unsummarized files.
- **One HTTP 400 error on LV_DCP** (`tests/unit/status/test_aggregator.py`): "We could not parse the JSON body of your request". The file content has characters that break OpenAI SDK's request serialization (possibly embedded triple backticks or control chars). Retried successfully on warm run. **Likely root cause**: embedded JSON-looking blobs in large test files confuse the SDK's payload construction. **Mitigation for Phase 5+**: escape content more aggressively in the user message, or submit as base64 with a decoder instruction.
- **Prompt v1 produces one factual hallucination**: "MCP = Managed Code Platform" in `libs/mcp_ops/doctor.py` summary, should be "Model Context Protocol". **Mitigation**: add a glossary section to the system prompt in v2, bump `prompt_version` to `v2` which invalidates old cache rows on that key component.
- **`ctx summarize` picks up non-code files** — Markdown templates, docs, plans get LLM summaries. Intended scope, but wastes tokens on files like `.specify/templates/spec-template.md`. **Mitigation for Phase 5+**: role-based filter in `summarize_project` skipping files where `role` is `"docs"` and size > threshold.
- **Cached column is misleading on cold run** (shows 57 cached across 508 files first time, but it's due to empty `__init__.py` content hash collisions across projects). Not a bug — cache is global on content hash, which means deduplication works correctly. Just UX clarity.

## Next up: Phase 3c.2

Vector search (BGE-M3 embeddings + sqlite-vec) + listwise rerank stage. Will use the **now-cached summaries from 3c.1** as embedding inputs — 405 summaries in `~/.lvdcp/summaries.db` are ready to feed the vector pipeline without re-calling LLM.

Targets: recall@5 files ≥ 0.92, impact_recall@5 ≥ 0.85.
