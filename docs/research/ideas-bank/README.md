# Банк идей из внешних GitHub-проектов

**Дата ресёрча:** 2026-04-21
**Методология:** 4 параллельных исследовательских агента прошли ~60 популярных (>500★) репозиториев по 4 направлениям: AI-кодинг-ассистенты, RAG/Graph-RAG/memory, парсинг+эмбеддинги+ранжирование, desktop-слой+Obsidian+MCP+observability.

## Как читать

Каждая идея оформлена карточкой:
- **Что даёт** простыми словами
- **Какую проблему решает** в LV_DCP
- **Где в коде сядет** (модуль)
- **Влияние** H / M / L
- **Срок** часы / дни / недели
- **Источник** — откуда идея

## Файлы

| Файл | Что внутри |
|------|------------|
| [`01-top10.md`](01-top10.md) | **Топ-10 идей** с максимальным ROI — критический путь |
| [`02-roadmap.md`](02-roadmap.md) | Раскладка по фазам (сейчас / фаза 2 / фаза 3) |
| [`03-retrieval.md`](03-retrieval.md) | Качество retrieval (эмбеддинги, ранжирование, чанкинг, query) |
| [`04-graph.md`](04-graph.md) | Графовый слой (PPR, communities, temporal edges, SCIP) |
| [`05-edit-safety.md`](05-edit-safety.md) | Edit pipeline (shadow-git, state machine, apply-model) |
| [`06-agent-desktop.md`](06-agent-desktop.md) | Desktop-агент (watchfiles, sync, launchd, block-hash) |
| [`07-privacy.md`](07-privacy.md) | Приватность (секреты, PII, context filters) |
| [`08-observability.md`](08-observability.md) | Observability + eval (Langfuse, promptfoo, ragas) |
| [`09-integrations.md`](09-integrations.md) | MCP, Obsidian, UX-паттерны |
| [`10-sources.md`](10-sources.md) | Полный список изученных репозиториев со звёздами |

## Ключевой вывод

Сильные внешние решения сходятся к **трём слоям**:
1. **Precise symbol index** (SCIP / tree-sitter) — у нас частично есть.
2. **Hybrid retrieval** (BM25 + dense + multivector + rerank) — у нас baseline, но можно удвоить качество.
3. **Edit safety** (shadow-git + apply-model + state-machine guard) — у нас **нет**, это приоритет фазы 2.

Если выбирать только 5 действий на ближайший спринт, это:
1. `bge-m3` как единый эмбеддер (dense + sparse + multivector) + `bge-reranker-v2-m3` на последней стадии
2. Matryoshka + binary quantization в Qdrant — экономия памяти до 32×
3. `watchfiles` вместо `watchdog` в desktop-агенте
4. `promptfoo` + `ragas` как eval harness (закрывает ADR-002)
5. `gitleaks` + `detect-secrets` гибрид в `libs/policies` (закрывает ТЗ §17)

Совокупный эффект оценивается в **+40–60% NDCG@10** на retrieval и полное закрытие privacy/eval контрактов за **~2 недели работы одного разработчика**.
