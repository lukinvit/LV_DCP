# Implementation Plan: RAGAS + promptfoo Eval Layer

**Branch**: `006-ragas-promptfoo-eval` | **Date**: 2026-04-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/006-ragas-promptfoo-eval/spec.md`

## Summary

Надстроить существующий eval harness (Phase 1, уже есть IR metrics + `@pytest.mark.eval` gate + polyglot suite) тремя delta-слоями:

1. **LLM-judge метрики** через RAGAS (Context Precision/Recall, Faithfulness).
2. **Promptfoo CI-gate** — PR-assertions с комментарием и fail-at-regression.
3. **History + diff** — `eval-results/*.json` + `ctx eval compare`.

Плюс — расширенные gold datasets (rare symbols, graph expansion, close siblings, edit tasks), которые блокируют валидацию SC для #1, #7, #9.

## Technical Context

**Language/Version**: Python 3.12 (как остальной проект).

**Primary Dependencies**:
- `ragas>=0.2.0` (LLM-judge фреймворк).
- `langchain-anthropic>=0.2.0` (провайдер для Claude-судьи).
- `anthropic>=0.40` (уже есть в зависимостях).
- `promptfoo` CLI (через npm, не pip; запускается `npx promptfoo@latest`).
- Никаких изменений в `libs/eval/metrics.py`.

**Storage**:
- Postgres — не трогаем.
- JSON-файлы `eval-results/YYYY-MM-DD-<sha>.json` (локально и в gh-release artifact).
- `tests/eval/baselines/main.json` — committed baseline, обновляется manual job.
- In-process LRU-cache для RAGAS responses (idempotency tests).

**Testing**:
- pytest-asyncio для RAGAS адаптера (unit + integration с mock-LLM).
- pytest для schema-валидации gold datasets.
- `make eval`, `make eval-full`, `make eval-ci` — разные режимы.

**Target Platform**:
- Dev: macOS (developer runs `make eval-full` occasionally).
- CI: Linux (GitHub Actions), nodejs 20 для promptfoo.
- Self-hosted CI: опционально, нужна та же конфигурация.

**Project Type**: library + CLI + CI workflow.

**Performance Goals** (см. spec SC):
- `make eval` ≤ 30 с (как сейчас).
- `make eval-full` ≤ 5 мин (+ RAGAS).
- CI eval job ≤ 10 мин (cold-start).

**Constraints**:
- Cost guard: ≤ $1 за `make eval-full`; > cost aborts.
- Zero регрессий на existing `@pytest.mark.eval` тестах.
- Никакого breaking change в `libs/eval/metrics.py`, `tests/eval/queries.yaml`, `thresholds.yaml`.

**Scale/Scope**:
- sample_repo — ~25 файлов (существует).
- Gold datasets — 60+ queries (20 navigate + 12 impact + 30 новых).
- Baseline: recall@5 = 0.964 (phase5-final).

## Constitution Check

*GATE: Must pass before Phase 0 research.*

- [x] ADR-002 — retrieval quality как контракт; #6 напрямую обслуживает.
- [x] ADR-001 budgets — cost guard FR-011 + CI total ≤ $10/day.
- [x] ТЗ §15 (async везде) — `run_ragas` использует async Anthropic client.
- [x] ADR-003 — eval только читает код, не пишет; single writer discipline не нарушается.
- [x] Privacy (#5) — eval на synthetic repo; если юзер запускает на реальном, inline scan должен быть в pipeline (отдельный concern, не блокирует #6).
- [x] Non-breaking: `libs/eval/metrics.py` и existing queries не трогаем.

**Re-check после Phase 1**: проверить фактический cost Claude Haiku для 32 queries × 4 RAGAS-метрики — при превышении $0.50 уменьшить выборку или кэшировать агрессивнее.

## Project Structure

### Documentation (this feature)

```text
specs/006-ragas-promptfoo-eval/
├── plan.md              # This file
├── spec.md              # Present
├── research.md          # Phase 0 — RAGAS/anthropic compatibility, promptfoo capabilities
├── data-model.md        # Phase 1 — JSON schema for eval-results, dataset YAML schema
├── quickstart.md        # Phase 1 — how to run eval-full locally
└── tasks.md             # Phase 2
```

### Source Code (repository root)

```text
libs/eval/
├── metrics.py              # UNCHANGED
├── runner.py               # MODIFY — add llm_judge arg, hook to ragas_adapter
├── report.py               # MODIFY — include ragas fields in output
├── loader.py               # MODIFY — support new dataset files
├── dataset_schema.py       # NEW — Pydantic schema for YAML gold datasets
├── ragas_adapter.py        # NEW — RAGAS wrapper with Anthropic judge
├── history.py              # NEW — save/load/compare eval runs
└── cost_guard.py           # NEW — tracks LLM spend, aborts on threshold

libs/core/
└── projects_config.py      # MODIFY — add EvalConfig sub-section

apps/cli/commands/
└── eval.py                 # MODIFY — add compare/history/run --full subcommands

tests/eval/
├── queries.yaml            # UNCHANGED
├── impact_queries.yaml     # UNCHANGED
├── thresholds.yaml         # UNCHANGED
├── datasets/
│   ├── rare_symbols.yaml           # NEW — for #1 US1
│   ├── close_siblings.yaml         # NEW — for #1 US2
│   ├── graph_expansion.yaml        # NEW — for #7
│   └── edit_tasks.yaml             # NEW — for #9
├── baselines/
│   └── main.json                   # NEW — committed baseline
├── promptfoo.config.yaml           # NEW — CI gate config
├── test_eval_harness.py            # UNCHANGED (existing thresholds test)
├── test_ragas_adapter.py           # NEW (unit with mock LLM)
├── test_history.py                 # NEW
└── test_dataset_schema.py          # NEW

tests/unit/eval/
└── test_metrics.py         # UNCHANGED

.github/workflows/
└── eval.yml                # NEW — promptfoo CI gate + baseline refresh job

Makefile                    # MODIFY — add eval-full, eval-ci targets

eval-results/               # NEW (runtime, .gitignore-d except last 5)
└── .gitkeep
```

## Phases

### Phase 0 — Research (before code)

Артефакт `research.md`:

1. Проверить совместимость RAGAS 0.2.x с `langchain-anthropic` + Claude Haiku 4.5. Минимальный smoke: `ragas.metrics.context_precision` на dummy dataset.
2. Стоимостная модель: 1 query в RAGAS = ~3 LLM calls × ~500 tokens = ~$0.002; 32 queries = ~$0.06 на Haiku.
3. promptfoo: `exec` provider vs HTTP provider; exec даёт лучшую изоляцию (запускает `ctx eval --json`).
4. Как снапшотить RAGAS results для determinism — проверить, есть ли cache в `ragas.run_config`.
5. Совместимость `@pytest.mark.eval` с новыми фикстурами (никаких breaking).
6. Как LLM-judge обрабатывает код (а не prose) — проверить на pilot из 5 queries.

### Phase 1 — Design

Артефакты `data-model.md`, `quickstart.md`.

1. **Dataset YAML schema** (Pydantic):
   ```python
   class GoldQuery(BaseModel):
       id: str
       query: str
       mode: Literal["navigate", "edit", "graph"]
       expected: Expected  # {files, symbols, optional answer_text}
       notes: str | None = None
       tags: list[str] = []
   ```
2. **EvalReport schema (extended)**:
   ```python
   class EvalReport:
       # existing
       recall_at_5_files: float
       precision_at_3: float
       mrr: float
       impact_recall_at_5: float
       # new
       ragas: RagasMetrics | None = None
       git_sha: str
       timestamp: datetime
       dataset_name: str
       judge_model: str | None
       per_query: list[QueryResult]
   ```
3. **DiffReport schema**:
   ```python
   class DiffReport:
       summary: dict[str, MetricDelta]  # metric -> {before, after, delta}
       per_query_deltas: list[QueryDelta]
       regressions: list[str]  # query ids with |delta| > 0.05
   ```
4. **Quickstart**:
   ```bash
   make eval                      # existing behaviour
   make eval-full                 # + RAGAS (ANTHROPIC_API_KEY required)
   ctx eval compare eval-results/A.json eval-results/B.json
   ctx eval history --limit 5
   npx promptfoo eval -c tests/eval/promptfoo.config.yaml
   ```

### Phase 2 — Implementation

См. `tasks.md`.

### Phase 3 — Validation

- `make eval-full` на sample_repo: собрать первый отчёт, зафиксировать baseline в `tests/eval/baselines/main.json`.
- `ctx eval compare` на двух отчётах: smoke-тест формата.
- Имитировать регрессию (stub с плохим retriever) → promptfoo падает, комментарий опубликован.
- Cost report: фактический spend < $0.50 (SC-002).
- Зеленые `@pytest.mark.eval` тесты (SC-006).

## Risks & Mitigations

| Риск | Impact | Mitigation |
|------|--------|-----------|
| RAGAS + anthropic несовместимость | H | Phase 0 smoke, fallback на OpenAI-провайдер если Haiku не работает |
| Cost LLM-judge > бюджет | M | `cost_guard.py` + `llm_judge_max_cost_usd`; кэширование per-query results |
| Promptfoo nodejs cold-start на GHA | M | Cache `~/.npm`, pin версию; таргет 10 мин, есть запас |
| Variance RAGAS numbers > 5% | M | Кэш per-query + seed; если вариативность не уходит — усреднение 3-х ран |
| LLM-judge плохо ранжирует код | M | Проверка на 5 pilot queries в Phase 0; при плохих numbers — custom prompt в `ragas_adapter` |
| Baseline устаревает | L | Manual CI job `baseline-refresh` на merge в main; label-triggered |

## Out of Scope

- Migration существующих metrics в ragas (они остаются отдельно).
- Live-dashboard (Grafana/Langfuse) — это item #10 (не в top-9).
- A/B testing разных prompt-версий — обслуживает promptfoo, но prompt registry (часть Langfuse) — out.
- Публичный API для eval (кто-то снаружи). Только internal.
