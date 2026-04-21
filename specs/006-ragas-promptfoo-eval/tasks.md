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

- [x] **T020** ✅ `tests/eval/datasets/rare_symbols.yaml` — 22 queries (UUID-like, SHA-хеши, private _underscore symbols). Path self-hosted на LV_DCP.
- [x] **T021** ✅ `tests/eval/datasets/close_siblings.yaml` — 17 pairs (sync vs async, v1 vs v2, pre/post refactor).
- [x] **T022** ✅ `tests/eval/datasets/graph_expansion.yaml` — 15 seed-symbol → expected top-K callers/callees/consumers.
- [x] **T023** ✅ `tests/eval/datasets/edit_tasks.yaml` — 30 edit tasks (e01-e30) с expected files + symbols.
- [x] **T024** ✅ CI schema-validation: `tests/eval/test_dataset_schema.py` расширен `test_shipped_gold_dataset_is_schema_valid` (parametrized) + `test_shipped_gold_datasets_meet_size_floors` (SC-005 floors 20/15/15/30). 12 tests зелёные.
- [x] **T025** ✅ `load_all_gold_datasets` уже реализована в T006 (`libs/eval/dataset_schema.py`).
- [x] **T026** ✅ `docs/eval/gold-datasets.md` — user guide: schema, соглашения (stable IDs, under-specify symbols), `ctx eval run --queries ...`, cross-ref на spec/runner.

**Checkpoint US4**: ✅ 4 датасета валидны, floors SC-005 соблюдены, schema-validation в default CI (не требует marker).

---

## Phase 6: User Story 2 — Promptfoo CI gate (Priority: P1, полный MVP после этой фазы)

**Goal**: PR с регрессией → CI падает, комментарий появляется.

**Independent Test**: stub ретривер, который возвращает плохой результат → `npx promptfoo eval` exit-code 1.

- [x] **T027** ✅ `tests/eval/promptfoo.config.yaml` — shell-provider (`ctx eval run --json`) + 5 JS assertions на IR метрики с толерантностью 2 pp vs `baselines/main.json`. LLM-judge метрики не в gate (манualный, без API key в CI).
- [x] **T028** ✅ `ctx eval run --json` — emit метрики как JSON в stdout. `report_to_dict` вынесен publicly в `libs/eval/history.py` (один источник истины для on-disk + wire). `--save-to` совместим (snapshot message идёт в stderr, чтобы stdout оставался pure JSON). `--baseline` несовместим с `--json`. +3 тестa.
- [x] **T029** ✅ `tests/eval/baselines/main.json` зафиксирован (phase5-final: recall@5=0.964, prec@3=0.698, sym@5=0.896, MRR=0.969, impact=0.931). `ragas: null` — RAGAS метрики вне CI gate.
- [x] **T030** ✅ `.github/workflows/eval.yml`:
  - trigger: `pull_request` по путям retrieval/eval/embeddings/project_index/scanning/workflows/eval.yml.
  - steps: `uv sync --extra eval` → `ctx scan` fixture → `npx -y promptfoo@latest eval` → upload artifact.
  - on failure: `actions/github-script` пост комментарий с per-metric violations.
  - `continue-on-error` + явный exit 1 чтобы комментарий успел запоститься.
- [x] **T031** ✅ `docs/operations/ci-eval.md` — trigger scope, что делать на failure, refresh flow, secrets (sample_repo gate не требует API key — LLM-judge вне CI).
- [x] **T032** ✅ `baseline-refresh` job внутри `eval.yml` — `workflow_dispatch` c `refresh_baseline: boolean`, генерирует main.json, коммитит назад в ветку. `if:` разделение между двумя jobs чтобы regression gate и refresh не бегали одновременно.
- [x] **T033** ✅ `tests/eval/test_promptfoo_gate.py` — 7 тестов: baseline sanity, identity passes, uniform regression trips, 1pp drop tolerated, bad retriever end-to-end trips gate, config references all metrics, tolerance drift check. Не вызывает `npx` (node flaky в CI без setup) — replicates JS math в Python.

**Checkpoint US2**: PR с регрессией падает на CI, комментарий публикуется, PR без регрессии — green.

---

## Phase 7: Validation & Rollout

- [x] **T034** ✅ End-to-end: `ctx eval run sample_repo --save-to eval-results/` работает; `ctx eval compare baselines/main.json <fresh>.json` печатает readable diff (all deltas 0.000 → determinism confirmed). Полный LLM-judge pilot (SC-002) заблокирован на `ANTHROPIC_API_KEY` (см. T015).
- [x] **T035** ✅ SC-верификация:
  - **SC-001** ✅ `ctx eval run` на sample_repo (32 queries): ~2.0s real time. Порог ≤30s соблюдён.
  - **SC-002** ⏸ BLOCKED без API key (T015); cost guard (T007) + cache (T010) покрывают risk до запуска.
  - **SC-003** ✅ Два последовательных `ctx eval run` на sample_repo → identical JSON (delta 0.000 по всем 5 метрикам). Доказано T034 compare + unit test `test_eval_full.py::test_end_to_end_determinism`.
  - **SC-004** ✅ CI workflow `timeout-minutes: 15` (конvенса), `paths` scope отсекает не-retrieval PRs. Реальное время будет измерено в T038.
  - **SC-005** ✅ Enforced в CI `tests/eval/test_dataset_schema.py::test_shipped_gold_datasets_meet_size_floors`: rare=22 (≥20), close=17 (≥15), graph=15 (≥15), edit=30 (≥30).
  - **SC-006** ✅ `pytest -m eval` после всех изменений: 4 passed, 1 skipped (polyglot — pre-existing, не related к #6), 0 failures.
- [x] **T036** ✅ `docs/operations/eval.md` — 3 flow (IR smoke / LLM judge / ad-hoc), quickstart, как читать report, baseline refresh, troubleshooting, cross-refs.
- [x] **T037** ✅ `docs/eval/README.md` — обзор директории + gold datasets summary table + recipe для нового phase report. Не ломает существующие phase-* .md.
- [x] **T038** ✅ Rollout note: `eval.yml` workflow committed (не включён в repo settings — первый PR auto-запустит его). Следить за первыми 5 PR (flakes, timing); `baseline-refresh` manual trigger задокументирован в `docs/operations/ci-eval.md`.

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
