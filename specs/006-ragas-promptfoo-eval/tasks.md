---
description: "Task list for RAGAS + promptfoo eval layer (delta-only)"
---

# Tasks: RAGAS + promptfoo Eval Layer

**Input**: Design docs from `specs/006-ragas-promptfoo-eval/`
**Prerequisites**: plan.md (present), spec.md (present), research.md (Phase 0), data-model.md (Phase 1).

**Tests**: обязательны — unit для RAGAS адаптера (с mock LLM), history/compare, dataset schema; integration через `make eval-full` на sample_repo.

**Organization**: сгруппированы по user story; US1 — MVP.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: параллельно (разные файлы, нет зависимостей)
- **[Story]**: US1/US2/US3/US4 из spec.md
- Пути относительно репо-корня

## Path Conventions

- `libs/eval/` — библиотека
- `tests/eval/` — harness + datasets
- `apps/cli/commands/eval.py` — CLI
- `.github/workflows/` — CI

**Non-breaking baseline**: все задачи должны оставлять existing `@pytest.mark.eval` зелёным и не менять `libs/eval/metrics.py` / `tests/eval/queries.yaml` / `thresholds.yaml`.

---

## Phase 1: Setup (Shared Infrastructure)

- [x] **T001** ✅ Добавлено `ragas>=0.4.3` в `[project.optional-dependencies] eval`. Phase 0 smoke passed → `langchain-anthropic` **не добавлен** (native `provider='anthropic'`); см. `research.md`.
- [x] **T002** ✅ `libs/core/projects_config.py` расширен секцией `EvalConfig` (`judge_model`, `llm_judge_max_cost_usd`, `cache_ragas_responses`).
- [x] **T003** ✅ `Makefile` обновлён — цели `eval-full` и `eval-ci` добавлены.
- [x] **T004** ✅ `.gitignore` игнорирует `eval-results/*`, сохраняя `.gitkeep`.
- [x] **T005** ✅ `eval-results/.gitkeep` создан.

---

## Phase 2: Foundational (Blocking Prerequisites)

- [x] **T006** ✅ `libs/eval/dataset_schema.py` — `GoldQuery` + `load_gold_dataset` / `load_all_gold_datasets` реализованы (field `text`, не `query`, для консистентности с `queries.yaml`).
- [x] **T007** ✅ `libs/eval/cost_guard.py` — `CostGuard(max_usd)` + `incur(...)` + `CostGuardExceeded`; цены из `libs/llm/cost.py`.
- [x] **T008** ✅ Unit tests: `tests/eval/test_dataset_schema.py` (7 tests), `tests/eval/test_cost_guard.py` (6 tests).
- [x] **T009** ✅ Checkpoint зелёный — 13 тестов dataset/cost_guard.

---

## Phase 3: User Story 1 — LLM-judge метрики (Priority: P1, MVP часть 1)

**Goal**: `make eval-full` возвращает RAGAS метрики; две последовательных ран даёт identical numbers.

**Independent Test**: integration-тест с mock Anthropic клиентом; ассертить presence полей и determinism при включённом кэше.

- [x] **T010** ✅ `libs/eval/ragas_adapter.py`:
  - `RagasAdapter` (builder-kwargs, llm_override support для тестов, cache_enabled).
  - `async run(samples) -> RagasMetrics` — 3 метрики (`context_precision`, `context_recall`, `faithfulness`). `answer_relevancy` **отложен** — требует отдельный `BaseRagasEmbedding` (documented в docstring).
  - LLM через `ragas.llms.llm_factory(model, provider='anthropic', client=anthropic.Anthropic(api_key))`.
  - Class imports: `from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness`.
  - Per-key SHA256 cache (не lru_cache — нужно count hits/misses).
- [x] **T011** ✅ `libs/eval/runner.py`: `run_eval` остался sync (backward-compat с 26 callers). Added: `FileReader`, `default_file_reader`, `async def enrich_with_ragas(...)`. `EvalReport.ragas: RagasMetrics | None = None`.
- [x] **T012** ✅ `libs/eval/report.py::generate_per_query_report` — «LLM-judge metrics» section + `cp / cr / f` колонки в per-query таблице. +5 unit-тестов. Reports без `ragas` рендерятся без изменений.
- [x] **T013** ✅ Unit тесты: `tests/eval/test_ragas_adapter.py` (9 tests) — `MagicMock(spec=InstructorBaseRagasLLM)` удовлетворяет ragas isinstance-check, покрыты: all-metrics-fire, skip по missing fields, cache hits, cost_guard incrementation + exception.
- [x] **T014** ✅ Integration test: `tests/eval/test_eval_full.py` (markers `eval + llm`) — 3 теста: end-to-end wiring, determinism с кэшем, cache hits на duplicate queries.
- [ ] **T015** [US1] Pilot-проверка (manual, не CI): запустить `make eval-full` реально на Claude Haiku; записать первые numbers + cost; если cost > $0.50 — настроить кэш агрессивнее. **BLOCKED** — требует `ANTHROPIC_API_KEY` в env.

**Checkpoint US1**: `make eval-full` работает, produces JSON с RAGAS полями, cost < $0.50, determinism подтверждён.

---

## Phase 4: User Story 3 — History + diff (Priority: P2, но идёт здесь для CLI MVP)

**Goal**: `ctx eval compare`, `ctx eval history` — подкоманды работают.

**Independent Test**: два фейковых snapshot JSON → ctx eval compare → expected output.

- [x] **T016** ✅ `libs/eval/history.py` — `save_run` (atomic tmp+Path.replace), `load_run` (schema_version guarded), `compare` + `DiffReport` + `MetricDelta`, `latest_runs` (mtime sort, skips `.tmp-*`).
- [x] **T017** ✅ `tests/eval/test_history.py` — 13 tests: roundtrip with/without ragas, schema rejection, latest sort + limit + tmp-file skip, compare asymmetric ragas.
- [x] **T018** ✅ `apps/cli/commands/eval_cmd.py` переписан как Typer sub-app (`ctx eval run/compare/history`). `run` принимает `--save-to DIR` для snapshot; `compare` печатает markdown-таблицу per-metric deltas; `history` печатает table recent runs. `ctx eval` без subcommand → help.
- [x] **T019** ✅ `tests/unit/cli/test_eval_cmd.py` расширен 4 тестами (save_to, history empty, history with runs, compare roundtrip) + 5 существующих обновлены под `eval run <project>`.

**Checkpoint US3**: CLI работает, human-readable output, `ctx eval compare` в типовой ситуации ≤ 2 с.

---

## Phase 5: User Story 4 — Gold datasets для #1/#7/#9 (Priority: P1)

**Goal**: 4 новых YAML-файла с валидным schema; базовый smoke-run через harness.

**Independent Test**: `pytest tests/eval/test_dataset_schema.py` — все файлы валидны; `run_eval(stub_retrieve, queries=load_gold_dataset('rare_symbols.yaml'))` работает.

- [ ] **T020** [P] [US4] `tests/eval/datasets/rare_symbols.yaml` — 20+ entries с UUID, SHA-хешами, приватными/подчёркнутыми символами. Expected — пути из sample_repo или реальные из LV_DCP (self-hosting).
- [ ] **T021** [P] [US4] `tests/eval/datasets/close_siblings.yaml` — 15+ пар близких функций (sync/async, v1/v2).
- [ ] **T022** [P] [US4] `tests/eval/datasets/graph_expansion.yaml` — 15+ seed-symbol → expected top-K callers/callees (для #7).
- [ ] **T023** [P] [US4] `tests/eval/datasets/edit_tasks.yaml` — 30+ edit-задач (для #9): описание задачи + expected modified files + expected operations.
- [ ] **T024** [US4] CI schema-validation job — pytest `tests/eval/test_dataset_schema.py` запускается в default CI (не только eval).
- [ ] **T025** [US4] Расширить `libs/eval/loader.py`: функция `load_all_gold_datasets(names: list[str]) -> list[GoldQuery]`.
- [ ] **T026** [US4] Документация `docs/eval/gold-datasets.md` — как добавлять новые queries, соглашения.

**Checkpoint US4**: все 4 файла валидны, harness может их загрузить.

---

## Phase 6: User Story 2 — Promptfoo CI gate (Priority: P1, полный MVP после этой фазы)

**Goal**: PR с регрессией → CI падает, комментарий появляется.

**Independent Test**: stub ретривер, который возвращает плохой результат → `npx promptfoo eval` exit-code 1.

- [ ] **T027** [US2] `tests/eval/promptfoo.config.yaml`:
  ```yaml
  providers:
    - id: lvdcp-eval
      config:
        command: uv run ctx eval run --json
  tests:
    - vars: {dataset: queries}
      assert:
        - type: javascript
          value: output.metrics.recall_at_5_files >= baseline.recall_at_5_files - 0.02
  ```
- [ ] **T028** [US2] Добавить в `ctx eval run`: флаг `--json` для stdout-output (parseable promptfoo).
- [ ] **T029** [US2] `tests/eval/baselines/main.json` — зафиксировать текущий baseline (phase5-final numbers + свеже собранные RAGAS); commit.
- [ ] **T030** [US2] `.github/workflows/eval.yml`:
  - trigger: `pull_request`, `paths: ['libs/retrieval/**', 'libs/eval/**', 'libs/embeddings/**', 'tests/eval/**']`.
  - setup: Python 3.12, uv, nodejs 20, npm cache.
  - steps: `uv sync --extra eval`, `npx -y promptfoo@latest eval -c tests/eval/promptfoo.config.yaml --output promptfoo-output.json`, upload artifact.
  - on failure: `actions/github-script` → комментарий с diff table (из `promptfoo-output.json`).
- [ ] **T031** [US2] Secrets: `ANTHROPIC_API_KEY` в GH secrets (manual step, документировать в `docs/operations/ci-eval.md`).
- [ ] **T032** [US2] `actions/workflow_dispatch` job `baseline-refresh` — manual trigger для обновления `main.json`; label-gated.
- [ ] **T033** [US2] Simulation-тест (локально): stub retriever с `recall_at_5_files=0.80` → `npx promptfoo eval` → exit 1, stdout показывает регрессию.

**Checkpoint US2**: PR с регрессией падает на CI, комментарий публикуется, PR без регрессии — green.

---

## Phase 7: Validation & Rollout

- [ ] **T034** Full end-to-end: `make eval-full` на self-hosted LV_DCP indexed state; отчёт в `eval-results/` сохранён; `ctx eval compare` с phase5-final дал читаемый diff.
- [ ] **T035** [P] Проверить SC: SC-001 (≤30c), SC-002 (≤5 min, ≤$0.50), SC-003 (determinism), SC-004 (CI ≤10 min), SC-005 (datasets sizes), SC-006 (no regression).
- [ ] **T036** [P] Документация `docs/operations/eval.md`: как запускать локально, как читать отчёт, как обновлять baseline.
- [ ] **T037** [P] Обновить `docs/eval/README.md` — упомянуть новые датасеты и процесс.
- [ ] **T038** Rollout: включить eval.yml workflow, смержить baseline.json, мониторить первые 5 PR — adjustments по необходимости.

---

## Dependencies

- T001 → все Phase 3 (нужны зависимости).
- T006 → T010 (адаптер использует schema), T020–T023 (datasets валидируются schema).
- T016 → T018 (CLI использует history API).
- **US1 (T010–T015)** и **US4 (T020–T026)** могут идти параллельно.
- **US3 (T016–T019)** после US1.
- **US2 (T027–T033)** последней, требует baseline из US1 и datasets из US4.

## Non-goals

- Переписать `libs/eval/metrics.py`.
- Заменить polyglot eval.
- Live dashboard (Langfuse — item #10).
- Custom metric beyond RAGAS-provided.
- Integration с user-side eval (internal only).
