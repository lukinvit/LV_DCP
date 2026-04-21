# Feature Specification: Matryoshka + Binary Quantization in Qdrant

**Feature Branch**: `003-matryoshka-binary-quant`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #3 — храним компактные 256-битные векторы рядом с полными 1024-dim float. Первичный поиск — по binary (32× быстрее и дешевле по памяти), доранжировка top-50 — по full precision.

## User Scenarios & Testing

### User Story 1 — Снижение RAM при росте корпуса (Priority: P1)

Пользователь индексирует репо на 100k символов. Полный 1024-dim float индекс = 400 MB × несколько коллекций. Binary вектор (256 бит) даёт 32× экономию для основной структуры; full-precision остаётся на rescore.

**Why this priority**: ADR-001 жёстко лимитирует память; без квантизации не удержимся в бюджете на реальных корпусах.

**Independent Test**: `scripts/bench_qdrant_memory.py` на корпусе 50k точек показывает **<32 MB** для binary вместо ~400 MB для full; recall@10 теряет **<2 п.п.**

**Acceptance Scenarios**:

1. **Given** коллекция `devctx_symbols` с binary-квантизацией и 50k точками, **When** поиск top-50 по binary → rescore top-10 по full, **Then** NDCG@10 в пределах 2 п.п. от full-only режима.
2. **Given** та же коллекция, **When** замерен Qdrant peak RAM, **Then** ниже не-квантизованного baseline минимум в 20×.

---

### User Story 2 — Прозрачное включение для существующих коллекций (Priority: P2)

Опция `enable_binary_quant=true` в config активирует binary + rescore без ручной пересборки коллекции.

**Why this priority**: zero-downtime включение — часть operational excellence.

**Independent Test**: интеграционный тест: up коллекция без quant → включить quant → Qdrant автоматически строит binary index → поиск работает.

**Acceptance Scenarios**:

1. **Given** существующая коллекция без quant, **When** применён `QuantizationConfig(binary=...)`, **Then** Qdrant создаёт дополнительный binary index, full vectors остаются.

---

### User Story 3 — Matryoshka dimension truncation (Priority: P3)

Modern embedders (bge-m3, jina-v3) обучены возвращать осмысленные вектора при обрезке до 256/512/768-dim. Используем это для "mini-index" (ещё быстрее, чем binary — но 4× хуже recall).

**Why this priority**: усиление для spike-нагрузки; не обязательно на MVP.

**Independent Test**: sanity-check — обрезать 1024→256, NDCG@10 падает на <3 п.п.; параллельно binary даёт лучший baseline.

**Acceptance Scenarios**:

1. **Given** bge-m3 эмбеддинги, **When** truncate до 256-dim и rescore full-dim, **Then** NDCG@10 регрессирует менее чем на 3 п.п.

---

### Edge Cases

- Rescore pool слишком узкий (binary даёт плохой top-50) — увеличить pool до 100 через `oversampling` в Qdrant.
- Обновление модели → binary необходимо пересобрать → `ctx embeddings rebuild-quant` команда.
- Sparse vector не квантизуется — binary применяется только к dense (и colbert, если включен — но с меньшим выигрышем).
- Qdrant снапшоты — binary + full хранятся; restore возвращает оба.

## Requirements

### Functional Requirements

- **FR-001**: `QuantizationConfig` в `EmbeddingConfig` с полями `binary_enabled: bool`, `matryoshka_truncate_to: int | None`, `rescore_pool_size: int=50`.
- **FR-002**: `QdrantStore.ensure_collections()` MUST применять `quantization_config=QuantizationConfig(binary=BinaryQuantization(always_ram=True))` для dense-вектора при `binary_enabled=True`.
- **FR-003**: Search-вызовы MUST использовать `search_params=SearchParams(quantization=QuantizationSearchParams(rescore=True, oversampling=2.0))`.
- **FR-004**: При `matryoshka_truncate_to=N` MUST создаваться второй named vector `dense_mini` размерности `N`; при search стратегия two-stage — `dense_mini` для поиска pool, `dense` (full) для rescore.
- **FR-005**: CLI `ctx embeddings rebuild-quant --collection X` MUST пересобирать binary-индекс без пересчёта эмбеддингов.
- **FR-006**: Метрика `qdrant_quantization_recall_ratio` — экспериментальная, измеряется на periodic eval (`make eval --with-quant`).
- **FR-007**: Docker-compose MUST использовать Qdrant ≥ 1.10 (binary quant GA) / ≥ 1.12 (optimal Matryoshka API).

### Key Entities

- **QuantizationConfig** — DTO c binary/matryoshka settings, включается в `ensure_collections`.
- **Binary index** — internal Qdrant структура, генерируется автоматически при флаге.
- **Dense mini vector** — опциональный named vector усечённой размерности для Matryoshka.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Qdrant peak RAM на 50k точках **≤ 5%** от baseline (full-precision без quant) при включённом binary.
- **SC-002**: Retrieval latency (Qdrant search side) **≤ 50%** от baseline (binary быстрее из-за меньшего индекса).
- **SC-003**: NDCG@10 с binary + rescore **≥ 98%** baseline (без quant). Потеря допустима до 2 п.п.
- **SC-004**: С Matryoshka truncate=256 latency **≤ 30%** baseline; NDCG@10 ≥ 96%.
- **SC-005**: Rebuild-quant для коллекции 50k точек **< 2 мин** (binary строится из full в памяти Qdrant).

## Assumptions

- Qdrant доступен ≥ 1.10 в docker-compose.
- Binary quantization в Qdrant даёт заявленное 32× экономии (подтверждается их benchmark).
- Matryoshka работает только с эмбеддерами, обученными под это (bge-m3, jina-v3 — да; OpenAI text-embedding-3-small — частично).
- Накладывается на dense-ветку из #1; sparse/colbert не квантизуются (или квантизуются отдельно, вне скоупа).

## Dependencies & Constraints

- Зависит от: #1 (bge-m3) — для полноценного использования Matryoshka; binary quant работает и на OpenAI.
- Блокирует: ничего.
- Не конфликтует с: #2 (rerank применяется ПОСЛЕ Qdrant, бинарная квантизация не видна rerank-еру — он видит уже финальный pool).
- Constitution §27 — коллекции остаются фиксированные; quant — per-collection setting.
- ADR-001 — SC-001 напрямую обслуживает memory budget.
