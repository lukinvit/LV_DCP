# Feature Specification: RAGAS + promptfoo Eval Harness

**Feature Branch**: `006-ragas-promptfoo-eval`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #6 — `make eval` возвращает цифры (Context Precision@K, Context Recall@K, Faithfulness). Promptfoo — YAML-декларации тестов с CI-интеграцией; ragas — метрики как LLM-judges. ADR-002 требует retrieval quality как контракт.

## User Scenarios & Testing

### User Story 1 — Воспроизводимая метрика качества retrieval (Priority: P1)

Разработчик хочет знать: стал ли retrieval лучше после изменения. `make eval` запускает фиксированный набор запросов, сравнивает результаты с gold set, печатает delta NDCG@10/Recall@10/Precision@10 против предыдущего ran.

**Why this priority**: ADR-002 — retrieval quality как контракт; без этого все улучшения (#1, #2, #3, #7) — слепые.

**Independent Test**: `make eval` на фиксированной версии кода дважды даёт одинаковые numbers (determinism test); запуск после bge-m3 (#1) показывает ожидаемое улучшение.

**Acceptance Scenarios**:

1. **Given** пустая история eval, **When** `make eval` запущен на main, **Then** создан `eval-results/YYYY-MM-DD-sha.json` с метриками.
2. **Given** предыдущий ран сохранён, **When** `make eval` повторно, **Then** печатается сравнительная таблица `delta NDCG, delta Recall`.

---

### User Story 2 — Promptfoo YAML как контракт для CI (Priority: P1)

Pull request меняет код retrieval. CI автоматически запускает `promptfoo eval --config tests/eval/retrieval.promptfooconfig.yaml`, падает если любая assertion регрессирует.

**Why this priority**: без CI-gate регрессии проскакивают незаметно.

**Independent Test**: PR с заведомо плохим ретривером → CI падает с прозрачным сообщением о регрессии.

**Acceptance Scenarios**:

1. **Given** baseline numbers зафиксированы в promptfoo config, **When** PR вводит регрессию NDCG@10 на -5 п.п., **Then** CI job падает, комментарий с diff-таблицей публикуется в PR.

---

### User Story 3 — RAGAS LLM-judge метрики (Priority: P2)

`Context Precision`, `Context Recall`, `Faithfulness` — метрики через LLM-судью (anthropic/claude-haiku). Полезно для `make eval --with-llm-metrics` (медленнее, но богаче).

**Why this priority**: LLM-judge метрики ловят семантическое качество, которое NDCG не видит.

**Independent Test**: eval-suite с mock-LLM-judge (deterministic answers) ассертит, что метрики считаются и сохраняются.

**Acceptance Scenarios**:

1. **Given** включён `--with-llm-metrics`, **When** eval запущен, **Then** в отчёте есть поля `context_precision`, `context_recall`, `faithfulness` как числа [0,1].

---

### User Story 4 — Gold dataset curated by engineers (Priority: P2)

`tests/eval/datasets/` содержит YAML-файлы с query → expected files/symbols/chunks. Разработчик легко добавляет новый кейс.

**Why this priority**: без куратируемого dataset метрики бессмысленны.

**Independent Test**: CI валидирует YAML schema всех датасетов; отсутствующие expected files — ошибка.

**Acceptance Scenarios**:

1. **Given** YAML dataset с отсутствующим `expected_file`, **When** schema validation, **Then** ошибка с указанием строки.

---

### Edge Cases

- Eval на пустой Qdrant — нулевые метрики, но pipeline не падает.
- LLM-judge rate-limited — retry с бекоффом; `make eval` логирует и продолжает.
- Gold set drift: файл переименован → YAML устарел → CI флагает.
- Флаки (LLM-judge дал другой вердикт) — average across 3 runs; если variance > 10% → warning.

## Requirements

### Functional Requirements

- **FR-001**: `libs/eval/metrics.py` предоставляет functions: `ndcg_at_k`, `recall_at_k`, `precision_at_k`, `mrr`.
- **FR-002**: `libs/eval/runner.py::run_eval_suite(dataset_path, retrieval_fn, *, llm_judge: bool = False)` — главный entrypoint.
- **FR-003**: `tests/eval/datasets/` — YAML files, schema: `{version: int, name: str, queries: list[{id, query, expected: {files: [...], symbols: [...]}, notes: str}]}`.
- **FR-004**: `make eval` запускает базовый suite (NDCG, Recall, Precision); `make eval-full` — с LLM-judge.
- **FR-005**: Результаты пишутся в `eval-results/<date>-<sha>.json`; history tracking через `libs/eval/history.py`.
- **FR-006**: Promptfoo конфиг `tests/eval/retrieval.promptfooconfig.yaml` — YAML с providers, datasets, assertions; вызывает HTTP endpoint `/v1/retrieval/eval` backend-а или local function.
- **FR-007**: RAGAS интеграция: `libs/eval/ragas_adapter.py` — обёртка над `ragas.evaluate()`; LLM provider = `anthropic.claude-haiku` по дефолту.
- **FR-008**: CLI `ctx eval compare <run_a> <run_b>` — диффит два JSON отчёта.
- **FR-009**: GitHub Actions workflow `.github/workflows/eval.yml` запускает promptfoo на PR; публикует комментарий с таблицей.

### Key Entities

- **EvalDataset** — YAML-loaded structure с queries и expected.
- **EvalResult** — DTO `{dataset, metrics: dict, per_query: list[QueryResult], timestamp, git_sha}`.
- **EvalHistoryEntry** — запись для сравнения.
- **PromptfooConfig** — YAML-native структура promptfoo.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Базовый `make eval` (без LLM-judge) завершается за **≤ 30 с** на 50-query suite.
- **SC-002**: `make eval-full` (с LLM-judge) завершается за **≤ 5 мин** на 50-query suite.
- **SC-003**: Два последовательных запуска `make eval` на чистой кодобазе дают **identical numbers** (determinism).
- **SC-004**: CI eval job в PR занимает **≤ 10 мин** включая cold-start.
- **SC-005**: Gold dataset при старте содержит **≥ 30 queries**, **≥ 10** — hardcore edge-cases (rare symbols, semantic paraphrases).

## Assumptions

- Claude API key доступен в CI для LLM-judge (стандартная для Anthropic security практика через GH secrets).
- RAGAS актуальной версии работает с anthropic-провайдером (на момент 2026-04 — да, через `langchain-anthropic` шим).
- Promptfoo CLI устанавливается через npm; nodejs доступен в CI.
- Gold dataset поддерживается вручную и ревьюится в PR.
- LV_DCP-монорепо используется как главный eval target (self-hosting).

## Dependencies & Constraints

- **БЛОКЕР** для валидации SC любого из #1, #2, #3, #7 — без метрик остальные улучшения слепые.
- Независимо от: #4, #5, #8, #9.
- Constitution ADR-002 — прямое требование.
- ADR-001 — budget на LLM-judge: ~$0.50 за `make eval-full`; один в день.
- Privacy (#5): eval запускается на synthetic dataset, секретов не содержит.
