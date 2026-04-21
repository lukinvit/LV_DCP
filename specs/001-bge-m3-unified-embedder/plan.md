# Implementation Plan: bge-m3 Unified Embedder

**Branch**: `001-bge-m3-unified-embedder` | **Date**: 2026-04-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-bge-m3-unified-embedder/spec.md`

## Summary

Заменить dense-only эмбеддинговый пайплайн на унифицированный bge-m3 адаптер, который в один forward-pass отдаёт dense + sparse + multivector представления. Qdrant-коллекции мигрируют на named vectors схему; hybrid search поверх трёх векторов через RRF.

## Technical Context

**Language/Version**: Python 3.12 (async-first)
**Primary Dependencies**:
- `FlagEmbedding>=1.2.10` (bge-m3 model wrapper, BAAI)
- `qdrant-client[async]>=1.12` (named + sparse + multivector support)
- `torch>=2.2` (MPS/CUDA backends)
- `transformers>=4.40` (tokenizer)
- Опционально `sentence-transformers` не нужен — FlagEmbedding обёртка самодостаточна.

**Storage**:
- Qdrant 1.12+ (named vectors + sparse + multivector).
- Локальный кэш модели `~/.cache/huggingface/hub/`.
- Postgres — только миграционная таблица `embedding_model_migrations` (id, from_model, to_model, started_at, finished_at, points_total, points_migrated, status).

**Testing**: pytest-asyncio, TestContainers для Qdrant 1.12+; фикстура `bge_m3_adapter_fake` для юнитов, реальный bge-m3 — только под маркером `@pytest.mark.heavy`.

**Target Platform**:
- Dev: macOS (Apple Silicon, MPS)
- Prod: Linux, CPU-fallback допустим, CUDA — plus.

**Project Type**: library + CLI (`libs/embeddings/` + `apps/cli/commands/embeddings.py`).

**Performance Goals**:
- `embed_batch(100)` ≤ 3.0 s на MPS, ≤ 1.5 s на CUDA (SC-002).
- Migration 5k символов ≤ 10 мин (SC-003).

**Constraints**:
- Хранение: ≤ 1.8× baseline (SC-005) — multivector дорогой, возможно ограничение `colbert_on={summaries,symbols}` без `chunks`.
- Бюджет ADR-001: reality-check на количество GPU-часов для bulk re-embed корпоративного repo.
- Fallback к `OpenAIEmbeddingAdapter` обязателен (FR-008).

**Scale/Scope**:
- Типовой корпус — 10k–100k символов.
- Для LV_DCP-монорепо (референс) ~5k символов.

## Constitution Check

*GATE: Must pass before Phase 0 research.*

- [x] ТЗ §27 — используем фиксированный набор коллекций (`devctx_*`); named vectors внутри, НЕ per-project collections.
- [x] ТЗ §15 (async везде) — `BgeM3Adapter.embed_batch` исполняет модельный forward через `asyncio.to_thread` (PyTorch sync).
- [x] ADR-003 — backend остаётся единственным writer в Qdrant; агент не пишет.
- [x] ADR-001 budgets — memory/latency targets зафиксированы в SC.
- [x] Privacy — модель локальная, не шлёт данные наружу (в отличие от OpenAI).

**Re-check после Phase 1**: memory-footprint real numbers для multivector; может потребоваться ограничить multivector только `summaries` и `symbols`.

## Project Structure

### Documentation (this feature)

```text
specs/001-bge-m3-unified-embedder/
├── plan.md              # This file
├── spec.md              # Already written
├── research.md          # Phase 0 — bge-m3 vs alternatives (jina-v3, nomic), Qdrant named vectors capabilities matrix
├── data-model.md        # Phase 1 — Qdrant schema, payload, migration table
├── quickstart.md        # Phase 1 — how to enable bge-m3 locally
├── contracts/
│   └── adapter.pyi      # BgeM3Adapter stub, types for named vectors output
└── tasks.md             # Phase 2 — written by /speckit.tasks
```

### Source Code (repository root)

```text
libs/embeddings/
├── adapter.py              # EmbeddingAdapter protocol (existing) — add MultiVectorEmbeddingAdapter protocol
├── bge_m3.py               # NEW — BgeM3Adapter
├── qdrant_store.py         # MODIFY — named vectors config, upsert_multi, search_hybrid
├── service.py              # MODIFY — vector_search uses hybrid when adapter supports multi
├── chunker.py              # unchanged
└── migration.py            # NEW — collection migration + alias swap logic

apps/cli/commands/
└── embeddings.py           # NEW — `ctx embeddings migrate`, `ctx embeddings status`

libs/core/
└── projects_config.py      # MODIFY — add EmbeddingConfig.provider=bge_m3, bge_m3_* knobs

tests/
├── unit/embeddings/
│   ├── test_bge_m3_adapter.py           # NEW — uses fake/stub model
│   ├── test_qdrant_named_vectors.py     # NEW
│   └── test_qdrant_store.py             # MODIFY — parametrize over adapter types
├── integration/embeddings/
│   ├── test_hybrid_search.py            # NEW — spins Qdrant, fake vectors
│   └── test_migration.py                # NEW — v1 collection → v2 migration
└── eval/datasets/
    └── rare_symbols.yaml                # NEW — 20+ query/expected pairs for US1

scripts/
└── bench_embedder.py                    # NEW — latency benchmark (US3)
```

## Phases

### Phase 0 — Research (before code)

Артефакт `research.md`:

1. Сравнить bge-m3 vs jina-embeddings-v3 vs nomic-embed-text-v1.5: matrix (size, languages, sparse support, license).
2. Qdrant capability check: версия on-prem; multivector + sparse в одной коллекции; RRF fusion API.
3. Fallback-стратегия: когда bge-m3 недоступен (макбук без 5 GB свободно), какой adapter работает.
4. Memory footprint расчёт: 5k символов × (1024 × 4 + sparse~100 × 8 + multivector ~50 × 1024 × 4) → ~20 MB диск/чанк × всё.

### Phase 1 — Design

Артефакты `data-model.md`, `quickstart.md`, `contracts/`.

1. Qdrant schema финализирована:
   ```
   vectors_config = {
     "dense":   VectorParams(size=1024, distance=Distance.COSINE),
     "colbert": VectorParams(size=1024, distance=Distance.COSINE,
                             multivector_config=MultiVectorConfig(comparator=MultiVectorComparator.MAX_SIM))
   }
   sparse_vectors_config = {
     "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
   }
   ```
2. Payload расширен: `model_version`, `vector_kinds: list[str]`, `dim_dense`, `dim_colbert`.
3. Протокол `MultiVectorEmbeddingAdapter`:
   ```python
   class MultiVectorEmbeddingAdapter(Protocol):
       model_name: str
       dimension: int
       async def embed_batch_multi(
           self, texts: Sequence[str],
           *, dense: bool = True, sparse: bool = True, colbert: bool = True,
       ) -> BatchMultiVectorResult: ...
   ```
4. Миграционная таблица Postgres `embedding_model_migrations` — Alembic ревизия.
5. Quickstart: `uv run ctx embeddings migrate --to bge-m3` + env `EMBEDDINGS__PROVIDER=bge_m3`.

### Phase 2 — Implementation

См. `tasks.md`.

### Phase 3 — Validation

- `make eval` (после item #6 реализован) показывает SC-001.
- `scripts/bench_embedder.py` подтверждает SC-002.
- `test_migration.py` подтверждает SC-003.
- Snapshot before/after через Qdrant snapshot API.

## Risks & Mitigations

| Риск | Impact | Mitigation |
|------|--------|-----------|
| bge-m3 слишком тяжёл для dev-машин | H | CPU fallback + OpenAI fallback (FR-008); docker worker с pre-warm |
| Qdrant версия в проде < 1.10 | H | Gate в `alembic upgrade`, требовать ≥1.10; compose файл обновлён |
| Multivector взрывает storage | M | В данных SC-005; если превысим — отключить `colbert` для `devctx_chunks`, оставить для `symbols`/`summaries` |
| Миграция зависает при крупном корпусе | M | Chunked migration с checkpoint в `embedding_model_migrations`; возобновление |
| RRF weights не оптимальны по дефолту | L | Конфигурируемые веса в `EmbeddingConfig.fusion_weights`; дефолт из Qdrant best practice |

## Out of Scope

- Дообучение bge-m3 на код-корпусе (последующая идея).
- Multi-lingual eval — базовый suite — английский/русский + код.
- Rerank (отдельная спека #2).
- Matryoshka/binary quant (отдельная спека #3).
