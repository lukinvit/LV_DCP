---
description: "Task list for bge-m3 unified embedder (dense + sparse + multivector)"
---

# Tasks: bge-m3 Unified Embedder

**Input**: Design documents from `specs/001-bge-m3-unified-embedder/`
**Prerequisites**: plan.md (present), spec.md (present), research.md (Phase 0), data-model.md (Phase 1)

**Tests**: обязательны — unit для адаптера и конфигов, integration с Qdrant (TestContainers), eval-fixture для US1.

**Organization**: сгруппированы по user story; US1 — MVP.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимостей)
- **[Story]**: US1/US2/US3 из spec.md
- Пути абсолютные относительно репо-корня

## Path Conventions

- `libs/embeddings/` — библиотека
- `libs/core/projects_config.py` — конфиги
- `apps/cli/commands/` — CLI
- `tests/` — тесты

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: зависимости, конфиги, фикстуры.

- [x] **T001** Добавить `FlagEmbedding`, `transformers`, `torch` в `pyproject.toml` (секция `[project.optional-dependencies] bge-m3`); `torch` без CUDA-вариации, Apple Silicon тянет MPS через `torch` напрямую.
- [x] **T002** [P] Обновить `libs/core/projects_config.py`: добавить `EmbeddingConfig.provider: Literal["openai","ollama","bge_m3","fake"]`, `bge_m3_device`, `bge_m3_use_sparse`, `bge_m3_use_colbert`, `fusion_weights`.
- [x] **T003** [P] Обновить `docker-compose/backend.yml` — Qdrant 1.12+; worker image получает `HF_HOME=/models` volume. *(Qdrant уже на 1.13.6; HF_HOME контракт задокументирован в `deploy/docker-compose/qdrant.yml`; worker-образ — позже.)*
- [x] **T004** Alembic ревизия `embedding_model_migrations` (id UUID, project_id UUID FK, from_model, to_model, started_at, finished_at TIMESTAMPTZ NULL, points_total, points_migrated, status ENUM{running, done, failed}). *(Адаптировано: таблица живёт в `SqliteCache` через миграцию схемы v4→v5 до появления Postgres/Alembic-инфраструктуры.)*
- [x] **T005** [P] Фикстуры pytest: `tests/conftest.py` → `bge_m3_fake_adapter` (deterministic hash vectors of required shapes).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: базовые абстракции, без которых US1 не заработает.

- [x] **T006** В `libs/embeddings/adapter.py` добавить `MultiVectorEmbeddingAdapter(Protocol)` с методом `embed_batch_multi(texts, *, dense, sparse, colbert) -> BatchMultiVectorResult`. `BatchMultiVectorResult` — dataclass с полями `dense: list[list[float]] | None`, `sparse: list[SparseVec] | None`, `colbert: list[list[list[float]]] | None`.
- [x] **T007** В `libs/embeddings/bge_m3.py` реализовать `BgeM3Adapter` (использует `FlagModel`/`BGEM3FlagModel` из FlagEmbedding; `torch` forward под `asyncio.to_thread`). Device: MPS → CUDA → CPU (auto-detect).
- [x] **T008** В `libs/embeddings/qdrant_store.py`: переписать `ensure_collections()` под named vectors — `vectors_config={dense: VectorParams, colbert: VectorParams(multivector_config=...)}`, `sparse_vectors_config={sparse: SparseVectorParams}`. Добавить `upsert_multi(collection, points: list[MultiVectorPoint])`. *(`ensure_collections(hybrid=True)` — колбert+sparse slots; `hybrid=False` сохраняет dense-only back-compat для OpenAI/Ollama.)*
- [x] **T009** Реализовать `QdrantStore.search_hybrid(collection, query_vectors: QueryVectors, filter, limit) -> list[ScoredPoint]` через Qdrant `query_points` API с `Fusion.RRF`. *(Project-id filter applied на prefetch-уровне + outer query — cross-project leak невозможен.)*
- [x] **T010** **Checkpoint**: все unit-тесты `T006–T009` зелёные; можно перейти к US1 и далее. *(808 unit-тестов green; 16 qdrant_store + 11 bge_m3 + 8 fake adapter.)*

---

## Phase 3: User Story 1 — Rare-identifier lookup (Priority: P1, MVP)

**Goal**: поиск по редким идентификаторам работает через hybrid (dense+sparse).

**Independent Test**: новый eval-датасет `tests/eval/datasets/rare_symbols.yaml`; метрика Recall@5 поднимается с <0.4 (dense-only) до >0.8.

- [x] **T011** [US1] Создать `tests/eval/datasets/rare_symbols.yaml` с 20+ парами (query, expected_file/symbol): UUID, SHA-хеши, приватные имена, специфичные токены. *(24 пары; каждая строка self-contained — содержит `query`, `target_file`, `target_text` — чтобы synthetic corpus в T012 строился прямо из датасета.)*
- [x] **T012** [US1] Integration-тест `tests/integration/embeddings/test_hybrid_search.py`: TestContainer Qdrant 1.12, fake multi-vector adapter, ассертит hybrid > dense-only по Recall@5 на rare_symbols. *(Использован `AsyncQdrantClient(location=":memory:")` — поддерживает named vectors + sparse + multivector, TestContainers не требуется для функциональной проверки US1. Corpus = 24 target + 150 distractor docs; ассерты: hybrid > 0.8, dense-only < 0.4, `hybrid − dense > 0.4`.)*
- [x] **T013** [P] [US1] Модифицировать `libs/embeddings/service.py::vector_search` — если adapter поддерживает `MultiVectorEmbeddingAdapter`, использовать `search_hybrid`; иначе — существующий dense path (совместимость с OpenAI/Ollama).
- [x] **T014** [US1] Добавить `libs/embeddings/service.py::embed_project_files_multi()` — новая ветка для MultiVector adapter; используется в worker'е при `provider=bge_m3`. *(Адаптировано: вместо параллельной функции добавлен auto-dispatch в `_do_embed` через `_is_multi_vector(adapter)` — один entry-point, routing выбирает `_embed_and_upsert_multi` vs `_embed_and_upsert`. Воркер/сканер остаются на `embed_project_files`, который автоматически попадает в hybrid-ветку при `provider=bge_m3` или `fake_bge_m3` и не требует изменений API.)*
- [x] **T015** [US1] Unit-тест: `test_vector_search_routes_to_hybrid_when_adapter_is_multi`; мок adapter с/без MultiVector protocol.
- [x] **T016** [US1] Запустить `pytest tests/unit/embeddings tests/integration/embeddings -k "hybrid or rare"` — все зелёные. *(10/10 passed за 0.83 s; hybrid Recall@5 = 1.000 ≫ 0.8, dense Recall@5 ≈ 0.00 ≪ 0.4.)*

**Checkpoint US1**: rare-identifier Recall@5 ≥ 0.8 на eval-датасете; эта же MVP-веха разблокирует item #2 (reranker). *(✅ Достигнуто на synthetic fake-adapter корпусе; реальные bge-m3 latency/throughput метрики закрывает Phase 5 US3 bench; реальные Recall@5 числа — после item #6 eval harness.)*

---

## Phase 4: User Story 2 — Multivector token-level precision (Priority: P2)

**Goal**: различение близких вариантов (sync/async, v1/v2) через ColBERT-style multivector.

**Independent Test**: `tests/eval/datasets/close_siblings.yaml` — пары близких символов; accuracy выбора правильного варианта +15 п.п. над dense-only.

- [ ] **T017** [US2] `tests/eval/datasets/close_siblings.yaml` — 15+ пар «близнецов».
- [ ] **T018** [US2] Тест `test_hybrid_search.py::test_colbert_disambiguation` — включает multivector ветку RRF, ассертит accuracy.
- [ ] **T019** [US2] Настроить веса RRF в `EmbeddingConfig.fusion_weights = {dense: 1.0, sparse: 1.0, colbert: 0.7}` (дефолт); документировать в quickstart.
- [ ] **T020** [US2] Проверить memory footprint реальных данных (профилирование `scripts/bench_embedder.py --profile memory`); если multivector > SC-005 → ограничить `colbert_on_collections={summaries,symbols}`.

**Checkpoint US2**: disambiguation accuracy +15 п.п.; memory footprint в пределах SC-005.

---

## Phase 5: User Story 3 — Unified pipeline performance (Priority: P3)

**Goal**: `embed_batch` ≤ 1.3× baseline и SC-002 latency достигнуты.

**Independent Test**: `scripts/bench_embedder.py` даёт numbers под CI.

- [ ] **T021** [US3] `scripts/bench_embedder.py` (CLI argparse `--provider`, `--n-chunks`, `--output json`) — генерирует фиктивный корпус, измеряет p50/p95/p99 latency и throughput.
- [ ] **T022** [US3] CI job (GitHub Actions) `bench-embedder.yml` — запускается по схеме nightly + on-demand, сохраняет артефакт JSON, сравнивает с baseline.
- [ ] **T023** [US3] Проверить SC-002 на CPU (fallback) — вывести warning если latency × 3 > порог, но не падать.

**Checkpoint US3**: benchmark JSON присутствует, targets выполнены.

---

## Phase 6: Migration & Operations

**Purpose**: перевести существующие проекты на новую схему без downtime.

- [ ] **T024** [P] `libs/embeddings/migration.py`:
  - `plan_migration(project_id, from_model, to_model) -> MigrationPlan`
  - `run_migration(plan, resumable=True)` — создаёт временную коллекцию `devctx_*_v2`, реиндексирует батчами (500 точек), записывает прогресс в `embedding_model_migrations`.
  - `swap_alias()` — атомарное переключение alias `devctx_summaries -> devctx_summaries_v2`.
- [ ] **T025** [P] CLI `apps/cli/commands/embeddings.py`: команды `migrate --to bge-m3`, `status`, `rollback`.
- [ ] **T026** Integration-тест `tests/integration/embeddings/test_migration.py`: старая коллекция → новая, проверка консистентности payload, idempotency второго запуска (no-op <5 с).
- [ ] **T027** Документация `docs/operations/embeddings-migration.md` — quickstart, troubleshooting, rollback.

**Checkpoint**: migration 5k символов < 10 мин; повтор — no-op.

---

## Phase 7: Readiness, Observability, Rollout

- [ ] **T028** [P] `apps/backend/routes/readyz.py` — добавить проверку `adapter.healthcheck()` (non-empty dense), `Qdrant.get_collection` возвращает ожидаемую схему named vectors.
- [ ] **T029** [P] Метрики: `embeddings_fallback_total{from,to}`, `embeddings_latency_seconds{provider,kind}` (histogram), `embeddings_migration_progress{project_id}` (gauge).
- [ ] **T030** Feature-flag в `EmbeddingConfig.enable_bge_m3: bool = False` — rollout постепенный: dev → stage → prod.
- [ ] **T031** Smoke-тест в production: миграция на staging-проекте, проверка eval-метрик до/после (требует #6 eval harness).

**Checkpoint**: можно включить `enable_bge_m3=True` на первом проекте.

---

## Dependencies

- **T006 блокирует T007–T009** (протокол обязан появиться первым).
- **T008 блокирует T009** (collection schema до search_hybrid).
- **T010 (checkpoint)** обязан перед всеми US-фазами.
- **Item #2 (reranker)** READY после завершения Phase 3 (US1) — pool готов для rerank-а.
- **Item #3 (matryoshka/quant)** READY после Phase 4 — dense-ветвь стабильна для квантизации.
- **Item #6 (eval)** желателен до T031, но не блокирует сам код; можно использовать временные fixture-метрики.

## Non-goals

- Fine-tuning bge-m3 на код-корпусе.
- Замена OpenAI-compatible адаптера (он остаётся как fallback).
- Кросс-проектный transfer weights.
