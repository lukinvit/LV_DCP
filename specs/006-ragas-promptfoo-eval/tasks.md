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

- [ ] **T001** Добавить зависимости в `pyproject.toml`: `ragas>=0.2.0`, `langchain-anthropic>=0.2.0` в секцию `[project.optional-dependencies] eval`. Проверить импорт через `uv sync --extra eval`.
- [ ] **T002** [P] Расширить `libs/core/projects_config.py` секцией `EvalConfig` (`judge_model: str = "claude-haiku-4-5"`, `llm_judge_max_cost_usd: float = 1.0`, `cache_ragas_responses: bool = True`).
- [ ] **T003** [P] Обновить `Makefile`:
  ```
  eval:          # unchanged
  eval-full:     ## Run full eval with LLM judges
  	uv run ctx eval run --full --output eval-results/$(shell date +%Y-%m-%d)-$(shell git rev-parse --short HEAD).json
  eval-ci:       ## Run promptfoo gate (local sanity)
  	npx -y promptfoo@latest eval -c tests/eval/promptfoo.config.yaml
  ```
- [ ] **T004** [P] `.gitignore`: добавить `eval-results/` (keep-last-5 через pre-commit hook в future item).
- [ ] **T005** [P] `eval-results/.gitkeep` — создать папку.

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] **T006** `libs/eval/dataset_schema.py` — Pydantic schema для gold YAML: `GoldQuery` с полями `{id, query, mode, expected: {files, symbols, answer_text?}, notes?, tags}`; функция `load_gold_dataset(path) -> list[GoldQuery]`.
- [ ] **T007** [P] `libs/eval/cost_guard.py` — class `CostGuard(max_usd: float)` c методами `incur(tokens_in, tokens_out, model) -> None` (raises `CostGuardExceeded` при превышении); use `libs/llm/cost.py` как source of truth для цен.
- [ ] **T008** Unit тесты: `tests/eval/test_dataset_schema.py` (valid/invalid YAML), `tests/eval/test_cost_guard.py` (under/over threshold).
- [ ] **T009** **Checkpoint**: `pytest tests/eval -k "schema or cost_guard" -q` — зелёный.

---

## Phase 3: User Story 1 — LLM-judge метрики (Priority: P1, MVP часть 1)

**Goal**: `make eval-full` возвращает RAGAS метрики; две последовательных ран даёт identical numbers.

**Independent Test**: integration-тест с mock Anthropic клиентом; ассертить presence полей и determinism при включённом кэше.

- [ ] **T010** [US1] `libs/eval/ragas_adapter.py`:
  - class `RagasAdapter(judge_model: str, cost_guard: CostGuard)`.
  - `async run(queries, retrieved_contents) -> RagasMetrics` — вызывает ragas `context_precision`, `context_recall`, `faithfulness`, `answer_relevance`.
  - `langchain_anthropic.ChatAnthropic` как LLM.
  - Per-query cache: `functools.lru_cache` по `(query_hash, context_hash, metric)`.
- [ ] **T011** [US1] `libs/eval/runner.py::run_eval`: добавить аргумент `llm_judge: bool = False`; when True → вызов `RagasAdapter.run()`; добавить `ragas: RagasMetrics | None` в `EvalReport`.
- [ ] **T012** [P] [US1] `libs/eval/report.py`: extend `EvalReport.to_markdown()` — секция «LLM-judge metrics» при наличии `ragas`.
- [ ] **T013** [US1] Unit-тест `tests/eval/test_ragas_adapter.py`:
  - mock Anthropic client через `unittest.mock.patch("langchain_anthropic.ChatAnthropic.ainvoke")`.
  - ассертить: каждая метрика вызывается, cost_guard инкрементируется, cache перехватывает повтор.
- [ ] **T014** [US1] Integration-тест `tests/eval/test_eval_full.py` (marker `@pytest.mark.eval @pytest.mark.llm`): на sample_repo с кэшированными fixture-LLM ответами; ассертить determinism (два запуска → identical numbers).
- [ ] **T015** [US1] Pilot-проверка (manual, не CI): запустить `make eval-full` реально на Claude Haiku; записать первые numbers + cost; если cost > $0.50 — настроить кэш агрессивнее.

**Checkpoint US1**: `make eval-full` работает, produces JSON с RAGAS полями, cost < $0.50, determinism подтверждён.

---

## Phase 4: User Story 3 — History + diff (Priority: P2, но идёт здесь для CLI MVP)

**Goal**: `ctx eval compare`, `ctx eval history` — подкоманды работают.

**Independent Test**: два фейковых snapshot JSON → ctx eval compare → expected output.

- [ ] **T016** [US3] `libs/eval/history.py`:
  - `save_run(report: EvalReport, out_dir: Path) -> Path` — атомарное write через tmp + rename.
  - `load_run(path: Path) -> EvalReport`.
  - `compare(a: EvalReport, b: EvalReport) -> DiffReport`.
  - `latest_runs(dir: Path, limit: int) -> list[Path]`.
- [ ] **T017** [US3] Unit-тесты `tests/eval/test_history.py`: save/load round-trip, compare edges (missing queries, new metrics), latest_runs sort.
- [ ] **T018** [US3] CLI `apps/cli/commands/eval.py`:
  - `ctx eval compare <a> <b>` — печатает markdown-таблицу через `rich.table`.
  - `ctx eval history [--limit N]` — список последних runs с summary.
  - `ctx eval run [--full] [--output PATH]` — запуск + save.
- [ ] **T019** [US3] CLI-тесты `tests/unit/cli/test_eval_cmd.py` расширить (compare, history, run).

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
