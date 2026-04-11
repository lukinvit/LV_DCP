# ADR-001: Cost, latency and resource budgets

**Status:** Accepted
**Date:** 2026-04-10
**Supersedes:** —

## Context

ТЗ LV_DCP описывает амбициозную платформу, но не содержит ни одной жёсткой цифры стоимости или латентности. Опыт RAG-систем показывает, что без бюджетов проект неизбежно сползает в одну из ловушек: слишком медленный, слишком дорогой (LLM-стоимость), или слишком тяжёлый (память/диск). Каждое архитектурное решение должно приниматься **против конкретных числовых ограничений**, а не ощущений.

## Decision

Следующие бюджеты являются **контрактом**, а не целями. Превышение любого из них блокирует релиз фазы.

### 1. Latency budgets

| Операция | Фаза | Цель p50 | Потолок p95 |
|---|---|---|---|
| Initial scan, 500-файловый Python репо | 1 (deterministic) | 10s | 20s |
| Incremental scan, single-file change, end-to-end | 3 | 1.5s | 3s |
| Retrieval (context pack assembly) | 1 (deterministic) | 0.8s | 2s |
| CLI cold start (`ctx --help`) | все | 150ms | 400ms |

> Phase 2 closed without LLM summaries or vector stage (see ADR-004 pivot).
> LLM-specific latency and per-scan dollar cost budgets are defined in
> Phase 3c scope.

### 2. Cost budgets (LLM)

Все цены считаются по Claude API public pricing актуального на дату измерения. Кеш детерминированных промптов (content_hash + prompt_version → summary) считается **обязательным** — без него эти бюджеты недостижимы.

| Операция | Стоимость |
|---|---|
| Initial summarization канареечного репо LV_DCP (≈500 файлов Python) | ≤ $0.50 |
| Incremental summarization single-file change | ≤ $0.05 |
| Ежемесячный бюджет normal use (1 разработчик, 5–10 активных проектов) | ≤ $20 |
| Разовый cold-start индекс всех 25+ проектов workspace | ≤ $15 (one-time) |

Стоимость каждого scan'а **логируется в runtime** в structured log (`cost_usd`, `model`, `tokens_in`, `tokens_out`). Агрегат за день доступен через `ctx doctor cost`.

Кэш-хит по содержимому **не тарифицируется** — это главный рычаг соблюдения бюджета.

### 3. Resource budgets

| Ресурс | Потолок |
|---|---|
| Desktop agent процесс, steady state RSS | ≤ 200 MB |
| Desktop agent процесс, во время scan | ≤ 500 MB |
| SQLite local cache, на 1000 файлов | ≤ 50 MB |
| Postgres (backend), на 25 проектов × 500 файлов каждый | ≤ 2 GB (data), ≤ 200 MB (indexes) |
| Qdrant, фаза 5, на тот же объём | ≤ 1 GB на диск |
| `.context/*.md` артефакты на проект (500 файлов) | ≤ 500 KB суммарно |
| Размер одного context pack | 2 KB ≤ size ≤ 20 KB |

### 4. Retrieval quality budgets

Определены в [ADR-002](002-eval-harness.md), здесь только summary:

- Phase 1 exit: recall@5 ≥ 0.70 (deterministic-only)
- Phase 2 exit: recall@5 ≥ 0.85, precision@3 ≥ 0.70
- Phase 3a exit: не регрессировать Phase 2 thresholds после cleanup
- Phase 3c exit: recall@5 ≥ 0.92, impact_recall@5 ≥ 0.80 (LLM + vector enrichment)

## Consequences

### Positive
- Каждое архитектурное решение получает объективный тест.
- Регрессии стоимости и латентности ловятся автоматически, не на глаз.
- «Улучшения», которые делают хуже — отклоняются.

### Negative
- Дополнительная работа: runtime cost accounting, latency profiling, eval CI job.
- Возможные откаты, если фича превышает бюджет — больно, но правильно.
- Бюджеты нужно пересматривать по мере измерений — не все цифры выше измерены, некоторые обоснованные оценки.

### Operational
- Каждый PR, затрагивающий scan/retrieval/parsing, **должен** включать before/after числа.
- `make eval` в CI останавливает merge при превышении порогов.

## Alternatives considered

1. **No budgets, measure later** — отвергнуто. Опыт говорит, что retrofitted performance/cost ограничения в 3× дороже, чем design-time.
2. **Budgets only as guidance** — отвергнуто. Без блокирующего эффекта они игнорируются под давлением дедлайнов.
3. **Per-repo adaptive budgets** — отвергнуто на старте как преждевременная сложность. Один глобальный бюджет достаточно для фаз 0–3.
