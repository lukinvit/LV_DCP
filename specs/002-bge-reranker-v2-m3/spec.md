# Feature Specification: bge-reranker-v2-m3 Final Rerank Stage

**Feature Branch**: `002-bge-reranker-v2-m3`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #2 — маленький cross-encoder берёт топ-100 кандидатов из vector+graph и переранжирует в топ-20. Смотрит на пару (query, candidate) целиком, а не только на dot-product.

## User Scenarios & Testing

### User Story 1 — Снижение шума в top-20 (Priority: P1)

Пользователь получает pack и жалуется: «в top-5 висит функция, которая к задаче не относится». Cross-encoder смотрит на пару (query, текст кандидата) и даёт точный score, не зависящий от усреднённого эмбеддинга.

**Why this priority**: шумные top-20 — главная жалоба на retrieval; reranker дёшево чистит их.

**Independent Test**: на eval-suite (#6) NDCG@10 **+10–25 п.п.** поверх любого base-ретривера, при latency бюджете ≤ 300 мс на topK=100.

**Acceptance Scenarios**:

1. **Given** retrieval вернул 100 кандидатов с score по vector, **When** rerank применён, **Then** top-20 имеет NDCG@10 минимум +10 п.п. к baseline.
2. **Given** query «где JWT валидируется», **When** rerank работает, **Then** функция `validate_jwt()` выше по рангу, чем `create_user_token()` (даже если семантически близки).

---

### User Story 2 — Graceful degradation при latency spike (Priority: P2)

Если reranker не успел за budget (300 мс) — возвращаем исходный ранг без блокировки.

**Why this priority**: reranker — оптимизация, не блокер; SLA на retrieval не должен страдать.

**Independent Test**: искусственно замедлить reranker через `asyncio.sleep`; ассертить, что endpoint `POST /pack` отдаёт результат в срок, логирует `rerank_timeout_total`.

**Acceptance Scenarios**:

1. **Given** rerank занимает >300 мс, **When** вызван pipeline, **Then** возвращается base ранжирование, метрика `rerank_timeout_total{reason=budget}` инкрементирована.

---

### User Story 3 — Конфигурируемая пропорция pool/top (Priority: P3)

`rerank_pool=100, rerank_output=20` — дефолт; можно менять per project.

**Why this priority**: разные проекты имеют разный профиль (меньше файлов → меньше pool).

**Independent Test**: unit-тест config validation; integration — разные значения дают разные top-K размеры.

**Acceptance Scenarios**:

1. **Given** project config с `rerank_pool=30, rerank_output=5`, **When** pack запрошен, **Then** rerank выполнен на 30 кандидатах, возвращено 5.

---

### Edge Cases

- Pool пустой (retrieval не нашёл ничего) — rerank skip, no-op.
- Модель не загружена — fallback на base ранг, warning.
- Query длиннее max_length модели — обрезать до 512 токенов с отметкой в логах.
- Дубликаты в pool (одна файл два раза с разных граней) — dedupe до rerank по `(project_id, file_path, symbol_id)`.
- Стандартный cost — 100 пар × ~10 мс ≈ 1 с на CPU; на MPS ≤ 300 мс.

## Requirements

### Functional Requirements

- **FR-001**: Модуль `libs/retrieval/rerank.py` предоставляет `CrossEncoderReranker` с методом `async rerank(query: str, candidates: list[Candidate], *, top_k: int, timeout_ms: int) -> list[Candidate]`.
- **FR-002**: Реранкер MUST возвращать кандидатов, отсортированных по убыванию cross-encoder score, с добавленным полем `rerank_score` в DTO.
- **FR-003**: При превышении `timeout_ms` MUST вернуть `candidates[:top_k]` в исходном порядке (FR-002 к ним не применяется).
- **FR-004**: Реранкер MUST конфигурироваться через `RetrievalConfig.reranker = {model: str, pool_size: int, output_size: int, timeout_ms: int, device: str}`.
- **FR-005**: При недоступности модели (загрузка неуспешна) — fallback + warn, retrieval продолжается.
- **FR-006**: Метрики MUST включать `rerank_latency_ms` (histogram), `rerank_timeout_total`, `rerank_score_delta` (средний дельта-ранг по батчу).
- **FR-007**: Pipeline ordering: `summary → symbol → graph → vector → RERANK → raw snippets` (rerank вставляется ПЕРЕД финальным raw-expansion шагом).
- **FR-008**: CLI `ctx eval rerank` — запуск eval-сьют с/без rerank, вывод delta NDCG@10.

### Key Entities

- **Candidate** — DTO с полями `id`, `text` (обрезанный content для cross-encoder), `base_score`, `rerank_score` (null до rerank), `metadata`.
- **Reranker model** — `BAAI/bge-reranker-v2-m3` (мульти-language cross-encoder).
- **Rerank budget** — `timeout_ms` (default 300) + max `pool_size` (default 100).

## Success Criteria

### Measurable Outcomes

- **SC-001**: NDCG@10 на eval-suite (#6) поднимается минимум на **+10 п.п.** (соло metric) и **+15 п.п.** в сочетании с bge-m3 (#1).
- **SC-002**: p95 latency rerank для pool=100 ≤ 300 мс на MPS/CUDA; ≤ 800 мс на CPU.
- **SC-003**: Rerank-timeout rate < 1% в обычной эксплуатации.
- **SC-004**: Eval-запуск сравнения rerank vs base на CI — один воркфлоу в день.
- **SC-005**: Memory footprint модели ≤ 600 MB RAM (bge-reranker-v2-m3 ~550 MB).

## Assumptions

- `bge-reranker-v2-m3` через `FlagEmbedding.FlagReranker` или `sentence-transformers` CrossEncoder; протоколу одинаково.
- Работает вместе с любым base retriever — не требует #1 (но с ним эффективнее).
- Eval harness (#6) желателен для валидации SC-001, но FR/тестируемость на синтетическом датасете возможна без #6.
- Модель загружается один раз, переиспользуется между запросами (singleton в lifespan).

## Dependencies & Constraints

- Блокирует: ничего напрямую.
- Зависит от: ничего (работает над любым ретривером), но SC-001 валидируется через #6.
- Синергия: #1 (bge-m3) поставляет чище pool → rerank эффективнее.
- Budget: input +1 модель ~600 MB RAM; ADR-001 — окей при одном воркере.
