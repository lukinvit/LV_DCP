# Feature Specification: bge-m3 Unified Embedder (dense + sparse + multivector)

**Feature Branch**: `001-bge-m3-unified-embedder`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #1 — единый эмбеддер от BAAI (FlagEmbedding) даёт три типа векторов за один проход; все три пишутся в Qdrant как named vectors одной точки.

## User Scenarios & Testing

### User Story 1 — Точечный lookup редкого идентификатора (Priority: P1)

Разработчик спрашивает «где используется `_internal_parse_token`». Текущий dense-retrieval теряет редкие символы в семантическом шуме. Sparse-вектор (BM25-подобный) ловит такие токены идеально.

**Why this priority**: редкие идентификаторы — дневной хлеб IDE-интеграции. Без sparse-ветки мы не конкурентны с grep.

**Independent Test**: в `tests/eval/datasets/rare_symbols.yaml` (новый) готовится 20 пар (query, ожидаемый файл) с UUID, SHA-хешами, приватными именами. Метрика Recall@5 на dense-only vs dense+sparse должна подняться с <0.4 до >0.8.

**Acceptance Scenarios**:

1. **Given** коллекция `devctx_symbols` с 5k символами, **When** запрос = точное имя приватного метода, **Then** точка с этим символом в top-3 по hybrid score.
2. **Given** тот же корпус, **When** запрос = семантический перефраз («функция, парсящая JWT»), **Then** результат остаётся в top-10 (dense-ветка всё ещё работает).

---

### User Story 2 — Token-level precision через multivector (Priority: P2)

Для pack-запроса нужно различить две функции со схожей семантикой, но разными аргументами. Multivector (ColBERT-style) сравнивает пословно, а не суммарным вектором.

**Why this priority**: усиливает rerank-стадию (item #2) и позволяет различать близкие варианты одной функции (sync vs async, v1 vs v2).

**Independent Test**: датасет пар «близких» символов (`parse_user_sync`/`parse_user_async`, `v1_auth`/`v2_auth`). Метрика — accuracy выбора правильного варианта для disambiguation query. Цель: +15 pp над dense-only.

**Acceptance Scenarios**:

1. **Given** две функции с одинаковым именем в разных модулях, **When** запрос содержит сигнатуру аргумента, **Then** multivector-score выделяет правильную.

---

### User Story 3 — Унифицированный пайплайн (Priority: P3)

Один `BgeM3Adapter` возвращает все три типа векторов за один forward-pass модели. Не три отдельных вызова.

**Why this priority**: экономит латентность и GPU-часы, упрощает pipeline.

**Independent Test**: бенчмарк `scripts/bench_embedder.py` показывает, что эмбеддинг 1000 чанков через bge-m3 занимает **≤1.3×** времени эмбеддинга только dense через OpenAI-compatible API.

**Acceptance Scenarios**:

1. **Given** 1000 чанков, **When** вызов `embed_batch(return_dense=True, return_sparse=True, return_colbert=True)`, **Then** три массива возвращены синхронно, latency логируется, ошибка одного типа не отменяет остальные.

---

### Edge Cases

- Qdrant коллекция создана со старой схемой (dense-only) — миграция должна быть детектирована и предложен alembic-style upgrade в отдельной команде (`ctx embeddings migrate`).
- Модель недоступна локально — graceful fallback на `OpenAIEmbeddingAdapter` с warning и отметкой в payload `model_version="openai-fallback"`.
- Sparse vector пустой (короткий текст <5 токенов) — записывается `{}` без ошибки.
- MPS/CUDA недоступен — CPU-режим с ворнингом; latency budget увеличен 3×.
- Смена модели в середине проекта — точки с `model_version` старой модели помечаются stale, реиндекс запускается в фоне.

## Requirements

### Functional Requirements

- **FR-001**: Система MUST предоставлять `BgeM3Adapter` с интерфейсом, совместимым с `EmbeddingAdapter` protocol ([libs/embeddings/adapter.py](../../libs/embeddings/adapter.py)), плюс методы `embed_batch_multi(texts, *, dense=True, sparse=True, colbert=True)`.
- **FR-002**: Qdrant коллекции (`devctx_summaries`, `devctx_symbols`, `devctx_chunks`) MUST использовать named vectors: `dense` (1024-dim), `sparse` (SparseVector), `colbert` (multivector, variable-length).
- **FR-003**: Payload каждой точки MUST содержать `model_version` (`bge-m3-v1`, `openai-fallback`, etc.) и `vector_kinds` — список активных векторов для этой точки.
- **FR-004**: Hybrid search MUST комбинировать результаты через Qdrant `Query` API с `Fusion.RRF` (reciprocal rank fusion) по трём named vectors.
- **FR-005**: Конфигурация MUST позволять отключать любой из трёх типов векторов через `EmbeddingConfig` (`bge_m3_enable_sparse`, `bge_m3_enable_colbert`).
- **FR-006**: CLI `ctx embeddings migrate` MUST предоставлять идемпотентную миграцию старых коллекций — создать новую коллекцию → перенести payload → переиндексировать в фоне → переключить alias.
- **FR-007**: При старте системы `/readyz` проверка MUST тестировать, что модель загружена и возвращает непустой dense-вектор ожидаемой размерности.
- **FR-008**: Fallback-режим — если bge-m3 не доступен, система MUST продолжать работать на OpenAI-compatible адаптере с warning в логах и метрикой `embeddings_fallback_total`.

### Key Entities

- **Vector set** — набор именованных векторов одной точки Qdrant: `{dense: float[1024], sparse: {indices, values}, colbert: float[n][1024]}`.
- **Model version tag** — строка вида `bge-m3-v1`, хранится в payload, позволяет идентифицировать stale-точки при смене модели.
- **Named vector collection** — конфигурация Qdrant с `vectors_config: {dense: VectorParams, colbert: VectorParams(multivector_comparator=MAX_SIM)}`, `sparse_vectors_config: {sparse: SparseVectorParams}`.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Recall@10 на retrieval-eval suite (после #6) поднимается минимум на **+20 п.п.** относительно baseline (OpenAI text-embedding-3-small, dense-only).
- **SC-002**: Latency embed_batch(100 chunks) MUST быть ≤ 3.0 с на macOS (M-series, MPS) и ≤ 1.5 с на Linux+CUDA.
- **SC-003**: Миграция репозитория на 5k символов (smoke fixture) MUST проходить идемпотентно за <10 мин; повторный запуск — no-op <5 с.
- **SC-004**: Регресс на симантических запросах — NDCG@10 на eval suite не падает более чем на 2 п.п. (нет sacrificing dense-качества ради sparse).
- **SC-005**: Memory footprint Qdrant-коллекций растёт не более чем в 1.8× (sparse вносит минимум, multivector — основной вклад).

## Assumptions

- Модель bge-m3 распространяется под Apache-2.0, безопасна к on-prem деплою.
- Скачивание весов ~2.3 GB один раз; кэшируется в `~/.cache/huggingface/`; в docker-образе worker'а — pre-warm через multi-stage build.
- Qdrant версии ≥1.10 поддерживает multivector и sparse vectors в одной коллекции ([Qdrant docs](https://qdrant.tech/documentation/concepts/vectors/#multivectors)).
- MPS-backend для Apple Silicon даёт приемлемую производительность (подтверждается бенчмарками FlagEmbedding).
- Задача #3 (Matryoshka + binary quant) применяется ПОСЛЕ #1 — сначала named vectors, потом квантизация dense-ветви.
- Задача #2 (reranker) строится ПОВЕРХ #1 — multivector усиливает rerank pool, но не обязателен для работы reranker-а.

## Dependencies & Constraints

- Блокирует: #2 (reranker опирается на качественный pool), #3 (quant накладывается на dense-вектор из #1).
- Не блокирует: #4, #5, #6, #7 — независимы.
- Конституция: соблюдает ТЗ §27 (фиксированный набор коллекций, изоляция через payload).
- ADR-001 budgets: увеличение памяти контролируется в SC-005.
