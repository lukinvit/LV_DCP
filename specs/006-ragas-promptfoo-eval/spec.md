# Feature Specification: RAGAS + promptfoo Eval Layer (надстройка над существующим harness)

**Feature Branch**: `006-ragas-promptfoo-eval`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #6 — `make eval` возвращает цифры (Context Precision@K, Context Recall@K, Faithfulness). Promptfoo — YAML-декларации тестов с CI-интеграцией; ragas — метрики как LLM-judges. ADR-002 требует retrieval quality как контракт.

## Существующее (не выбрасываем, строим поверх)

LV_DCP уже имеет eval-инфраструктуру Phase 1:

- **[libs/eval/metrics.py](../../libs/eval/metrics.py)** — `recall_at_k`, `precision_at_k`, `mean_reciprocal_rank`, `impact_recall_at_k` (pure, без I/O).
- **[libs/eval/runner.py](../../libs/eval/runner.py), loader.py, report.py** — канонический harness, `EvalReport`/`QueryResult` DTO.
- **[tests/eval/queries.yaml](../../tests/eval/queries.yaml), impact_queries.yaml** — 20 + 12 gold queries на sample_repo.
- **[tests/eval/thresholds.yaml](../../tests/eval/thresholds.yaml)** — phase-gated thresholds (active phase 3: recall@5 ≥ 0.92, impact_recall@5 ≥ 0.85).
- **[tests/eval/run_polyglot_eval.py](../../tests/eval/run_polyglot_eval.py)** — cross-project eval (4 real repos).
- **tests/eval/test_eval_harness.py** — pytest wrapper с `@pytest.mark.eval`, падает если метрики < threshold.
- **[docs/eval/](../../docs/eval/)** — отчёты baseline → phase5-final (recall@5 = 0.964).
- **`ctx eval` CLI** — существует (tests/unit/cli/test_eval_cmd.py).
- **[bench/](../../bench/)** — devctx-bench как standalone pip package (retrieval-only).

Что задача #6 **НЕ делает** (чтобы избежать greenfield-дубляжа):
- Не переписывает `libs/eval/metrics.py`.
- Не меняет формат `queries.yaml` / `thresholds.yaml`.
- Не трогает `ctx eval` CLI (только расширяет подкомандами).
- Не ломает `@pytest.mark.eval` workflow.

## Что #6 добавляет (delta)

1. **LLM-judge метрики через RAGAS**: `Context Precision`, `Context Recall`, `Faithfulness`, `Answer Relevance` — семантические, ловят то, что recall@k не видит.
2. **Promptfoo YAML как CI-gate для PR**: декларативные assertions, комментарий в PR с diff-таблицей, exit-code 1 при регрессии.
3. **History + diff между ранами**: `eval-results/YYYY-MM-DD-<sha>.json` → `ctx eval compare A B` → human-readable delta.
4. **Расширение gold datasets**:
   - `rare_symbols.yaml` — под валидацию #1 (bge-m3 sparse ветка);
   - `graph_expansion.yaml` — под валидацию #7 (Personalized PageRank);
   - `close_siblings.yaml` — под #1 multivector.
5. **Cost-aware запуск**: `make eval` = быстрый (без LLM), `make eval-full` = полный (с RAGAS), `make eval-ci` = то, что гоняется в PR.

## User Scenarios & Testing

### User Story 1 — LLM-judge метрики на существующем harness (Priority: P1)

Разработчик хочет видеть не только recall@k, но и «получил ли pack достаточно контекста для ответа на вопрос» (Context Recall) и «не содержит ли pack лишнего шума» (Context Precision). Текущий harness эти семантические метрики не считает.

**Why this priority**: без LLM-judge невозможно оценить pack quality для edit-задач (где важно «достаточность», а не только «наличие»).

**Independent Test**: `make eval-full` на existing queries.yaml + sample_repo возвращает JSON с полями `context_precision`, `context_recall`, `faithfulness` как числа [0,1]. Определяем baseline — numbers фиксируются в первом ране.

**Acceptance Scenarios**:

1. **Given** queries.yaml с 20 навигационными запросами, **When** `make eval-full` запущен, **Then** отчёт содержит per-query и агрегированные RAGAS-метрики, LLM-calls логируются, total cost < $0.50.
2. **Given** фиксированный seed и cached LLM responses (fixture), **When** `make eval-full` запущен дважды, **Then** numbers идентичны (voice-in-box determinism через RAGAS `run_config.seed`).

---

### User Story 2 — Promptfoo CI gate на PR (Priority: P1)

Pull request меняет `libs/retrieval/pipeline.py`. CI запускает promptfoo config; он вызывает `ctx eval --baseline phase3 --json` и сравнивает с референсным baseline из main; регрессия > 2 п.п. → fail + PR-комментарий.

**Why this priority**: ADR-002 — quality как контракт; без CI-gate регрессии проскакивают, как `precision@3: 0.620 → 0.568` (реальная регрессия в истории).

**Independent Test**: PR с заведомо ломаным ретривером → promptfoo job → CI падает, комментарий с delta-таблицей появляется.

**Acceptance Scenarios**:

1. **Given** baseline зафиксирован в `tests/eval/baselines/main.json`, **When** PR с регрессией NDCG@10 на -5 п.п., **Then** GitHub Action падает, комментарий "eval regressed" опубликован.
2. **Given** PR без изменений retrieval, **When** CI запускает eval, **Then** delta ≤ threshold → success.

---

### User Story 3 — History + compare между ранами (Priority: P2)

`ctx eval compare eval-results/2026-04-20.json eval-results/2026-04-21.json` — читабельный diff: какие queries улучшились, какие упали, agregate delta.

**Why this priority**: помогает разбирать eval-failures (см. `docs/eval/3c2-failure-analysis.md` — ручная классификация; хотим автоматизировать).

**Independent Test**: две фейковых ран-записи → `ctx eval compare` → ассертить структуру вывода и numbers.

**Acceptance Scenarios**:

1. **Given** два snapshot-JSON, **When** `ctx eval compare A B`, **Then** stdout содержит таблицу `[query, metric, before, after, delta]`, сортированную по `|delta| desc`.

---

### User Story 4 — Gold datasets под upcoming items (#1, #7) (Priority: P1)

Без gold queries нельзя валидировать SC-001 для bge-m3 (#1) и PPR (#7). Эти фикстуры делаются ПЕРЕД реализацией #1 и #7.

**Why this priority**: тесно привязано к #1 и #7; без fixtures их SC нельзя измерить.

**Independent Test**: YAML-schema валидация; smoke-run `run_eval(stub_retrieve, queries=rare_symbols)` работает.

**Acceptance Scenarios**:

1. **Given** `tests/eval/datasets/rare_symbols.yaml` с 20+ entries (UUID, хеши, приватные имена), **When** harness загружает, **Then** каждая запись имеет `{id, query, expected: {files, symbols}}`.
2. **Given** `graph_expansion.yaml` с 15+ entries (seed-symbol → expected top-K callers/callees), **When** загружен, **Then** поля валидны.

---

### Edge Cases

- RAGAS LLM rate-limited → retry с backoff; если всё равно fail → отчёт помечен `partial=true`, не блокирует `make eval` (только `make eval-full`).
- Baseline JSON отсутствует (первый ран на ветке) → promptfoo skip-ит gate, логирует warning.
- Claude API недоступен (offline, no key) → `make eval-full` skip-ает RAGAS секцию, запускает базовый (detailed в stderr).
- Gold dataset противоречит sample_repo (symbol удалён) → CI линт падает с указанием файла/строки.
- История `eval-results/` растёт → `.gitignore` только json-ы > 30 дней, keep-last-5.

## Requirements

### Functional Requirements

- **FR-001**: Модуль `libs/eval/ragas_adapter.py` предоставляет `async run_ragas(queries, retrieved, *, judge_model) -> RagasMetrics` dto с полями `context_precision`, `context_recall`, `faithfulness`, `answer_relevance`.
- **FR-002**: Judge provider — Claude (`claude-haiku-4-5` по дефолту, конфиг через `EvalConfig.judge_model`); RAGAS-native `llm` обёрнут в `langchain-anthropic`.
- **FR-003**: `libs/eval/runner.py::run_eval` расширяется аргументом `llm_judge: bool=False`; при True — дополнительно вызывает `run_ragas`, добавляет метрики в `EvalReport`.
- **FR-004**: `libs/eval/history.py` предоставляет `save_run(report, sha) -> Path`, `load_run(path) -> EvalReport`, `compare(a, b) -> DiffReport`.
- **FR-005**: `tests/eval/promptfoo.config.yaml` — декларация eval для CI; использует `exec`-provider, который вызывает `ctx eval --json`.
- **FR-006**: `.github/workflows/eval.yml` — GitHub Action: ставит nodejs, запускает promptfoo, публикует комментарий через `actions/github-script` при регрессии > 2 п.п.
- **FR-007**: CLI расширение `ctx eval compare <a> <b>`, `ctx eval history`, `ctx eval run --full` (alias для `make eval-full`).
- **FR-008**: Makefile: `make eval` (без LLM, как сейчас), `make eval-full` (+ RAGAS), `make eval-ci` (promptfoo локально).
- **FR-009**: `tests/eval/datasets/` — новые YAML:
  - `rare_symbols.yaml` (для US1 из #1),
  - `close_siblings.yaml` (для US2 из #1),
  - `graph_expansion.yaml` (для #7),
  - `edit_tasks.yaml` (для #9).
  Каждый файл валидируется через `libs/eval/dataset_schema.py` (Pydantic).
- **FR-010**: `tests/eval/baselines/main.json` — зафиксированный baseline; обновляется через CI-job `baseline-refresh` (manual trigger) после merge в main.
- **FR-011**: Cost guard: `EvalConfig.llm_judge_max_cost_usd=1.0` — превышение → abort с ошибкой.
- **FR-012**: Observability: каждый ран логирует `eval_run_total`, `eval_llm_cost_usd`, `eval_duration_seconds` (structlog + metrics).

### Key Entities

- **EvalReport** (расширяется, не переписывается): добавляются поля `ragas: RagasMetrics | None`, `git_sha: str`, `timestamp: datetime`, `dataset_name: str`, `judge_model: str | None`.
- **RagasMetrics** (новый): `{context_precision: float, context_recall: float, faithfulness: float, answer_relevance: float, llm_calls: int, cost_usd: float}`.
- **DiffReport** (новый): `{metric: {before, after, delta}}`, `per_query_deltas: list[QueryDelta]`.
- **Baseline artifact** — JSON snapshot в `tests/eval/baselines/`.

## Success Criteria

### Measurable Outcomes

- **SC-001**: `make eval` на sample_repo завершается за **≤ 30 с** (без регрессии от current baseline).
- **SC-002**: `make eval-full` на sample_repo (20 navigate + 12 impact) завершается за **≤ 5 мин**, cost ≤ $0.50 (Claude Haiku).
- **SC-003**: Два последовательных запуска `make eval-full` с кэшем RAGAS дают **identical numbers** (detrminism); без кэша — variance ≤ 5% на LLM-метриках.
- **SC-004**: CI eval job в PR занимает **≤ 10 мин** включая cold-start промптфу и nodejs.
- **SC-005**: Новые gold datasets: `rare_symbols.yaml ≥ 20`, `graph_expansion.yaml ≥ 15`, `close_siblings.yaml ≥ 15`, `edit_tasks.yaml ≥ 30`.
- **SC-006**: Zero регрессий на existing `@pytest.mark.eval` тестах после FR-003 изменений.

## Assumptions

- Anthropic API key доступен в CI (GH secret `ANTHROPIC_API_KEY`).
- RAGAS ≥ 0.2.x работает с Anthropic через `langchain-anthropic` (проверить на Phase 0).
- `promptfoo` устанавливается как npm (`npx promptfoo@latest`); nodejs 20 в CI.
- Existing `@pytest.mark.eval` — gate, не ломается.
- Gold datasets ручно куратируются и ревьюятся в PR.

## Dependencies & Constraints

- **БЛОКЕР** для SC-валидации: #1 (bge-m3), #2 (reranker), #3 (quant), #7 (PPR) — без расширенных gold datasets и history-compare их SC измерять нечем.
- Независимо от: #4, #5, #8, #9 (но #9 использует `edit_tasks.yaml` из FR-009).
- Constitution ADR-002 — прямое требование.
- ADR-001 — cost guard FR-011; $1 на CI-job × 10 PR/day = $10/day upper bound.
- Privacy (#5): eval на synthetic sample_repo, секретов нет; если eval гоняется на реальном репо пользователя — inline scan обязателен.

## Scope разделение с существующим harness

| Компонент | Существует | #6 добавляет |
|-----------|-----------|--------------|
| recall@k, precision@k, MRR | да, `libs/eval/metrics.py` | — |
| impact_recall@k | да | — |
| `queries.yaml`, `impact_queries.yaml` | да | расширение через новые датасеты (FR-009) |
| `thresholds.yaml` phase-gated | да | — |
| `ctx eval` CLI | базовый | подкоманды compare, history, run --full |
| `@pytest.mark.eval` pytest gate | да | — |
| Polyglot eval | да | не меняется |
| Context Precision (RAGAS) | нет | FR-001, FR-003 |
| Context Recall (RAGAS) | нет | FR-001, FR-003 |
| Faithfulness (RAGAS) | нет | FR-001 |
| promptfoo CI gate | нет | FR-005, FR-006 |
| eval history + compare | нет | FR-004, FR-007 |
| Baseline artifact | нет | FR-010 |
