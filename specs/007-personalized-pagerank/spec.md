# Feature Specification: Personalized PageRank для Graph Expansion

**Feature Branch**: `007-personalized-pagerank`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #7 — при graph-стадии retrieval seed-ноды (символы из query) используются как personalization-вектор в PageRank над графом calls/imports/inherits. Важные callers/callees всплывают наверх. Заменяет грубый BFS, который даёт транзитивный мусор.

## User Scenarios & Testing

### User Story 1 — Релевантный graph expansion для symbol query (Priority: P1)

Пользователь спрашивает «что ломается, если изменить `validate_jwt`». Текущий BFS по N=2 hops возвращает 200+ символов: все, кто вызывает `validate_jwt`, + все, кто вызывает тех, и т.д. Personalized PageRank превращает это в 20 самых релевантных по структурной важности.

**Why this priority**: качество pack'а в edit-режиме напрямую зависит от graph стадии; BFS шумит.

**Independent Test**: `tests/eval/datasets/graph_expansion.yaml` — пары (symbol, expected_top20_callers_callees). Метрика Precision@20 при PPR vs BFS: +20 п.п.

**Acceptance Scenarios**:

1. **Given** граф на 5k символов LV_DCP-монорепо, **When** запрос по `validate_jwt`, **Then** top-20 PPR содержит ≥ 80% истинных dependencies (ручной gold), тогда как BFS даёт ≤ 60%.

---

### User Story 2 — Multi-seed PPR для cross-symbol query (Priority: P2)

Query содержит несколько символов («связь между `UserService` и `AuthMiddleware`»). Personalization вектор равномерный над seed-нодами, PPR находит «мосты» в графе.

**Why this priority**: реальные вопросы часто про отношения, не про один символ.

**Independent Test**: синтетический граф с известным "bridge node" → ассертить, что bridge в top-5.

**Acceptance Scenarios**:

1. **Given** два seed-символа с одной общей промежуточной функцией, **When** PPR запущен, **Then** промежуточная функция в top-5 по PPR score.

---

### User Story 3 — Конфигурируемый damping factor (Priority: P3)

`alpha=0.85` дефолт (классика). Проекты могут настраивать: меньше alpha = больше веса seed, больше alpha = дальше expansion.

**Why this priority**: различные repo-профили (deep call stacks vs flat) требуют разных alpha.

**Independent Test**: unit-тесты с разными alpha дают разную top-K; convergence guarantee.

**Acceptance Scenarios**:

1. **Given** `alpha=0.5`, **When** PPR запущен, **Then** top-K остаётся в 1-hop окрестности seed.

---

### Edge Cases

- Граф неполный (после partial scan) — PPR по имеющемуся подграфу без ошибки.
- Seed-ноды отсутствуют в графе (удалили символ) — fallback на BFS или vector-search, warning.
- Цикличные зависимости — PPR natively справляется (это его свойство).
- Огромный граф (>100k nodes) — PPR через networkx медленен; переключиться на `igraph` или precomputed transition matrix.
- Граф раздроблен на disconnected components — PPR работает внутри компоненты seed, остальные получают 0 score.

## Requirements

### Functional Requirements

- **FR-001**: Модуль `libs/graph/ppr.py::personalized_pagerank(graph: GraphLike, seeds: set[NodeID], *, alpha: float = 0.85, max_iter: int = 100, tol: float = 1e-6) -> dict[NodeID, float]`.
- **FR-002**: `libs/retrieval/graph_expand.py` MUST использовать PPR вместо BFS, когда `RetrievalConfig.graph_expansion.method = "ppr"` (дефолт).
- **FR-003**: Fallback на BFS при `method = "bfs"` или когда seeds пустые.
- **FR-004**: Граф загружается из Postgres `symbol_relations` table через `libs/graph/loader.py` в in-memory `networkx.DiGraph` (или `igraph.Graph` для >50k nodes).
- **FR-005**: Веса рёбер MUST учитываться: `calls` × 1.0, `imports` × 0.5, `inherits` × 1.5, `references` × 0.3 (настраиваемо).
- **FR-006**: CLI `ctx graph expand <symbol>` — показывает top-20 PPR neighbours + scores для отладки.
- **FR-007**: Caching: in-memory TTL cache на `(project_id, graph_hash)` → `DiGraph` на 5 минут; инвалидация по notification от writer-а.
- **FR-008**: Метрики: `graph_expansion_duration_ms{method}`, `graph_expansion_result_size{method}`, `ppr_iterations_total`.

### Key Entities

- **GraphLike** — protocol: `.out_edges(node)`, `.weight(edge)`, `.nodes`, `.edges`.
- **PPRConfig** — `{alpha, max_iter, tol, edge_weights: dict[relation_type, float]}`.
- **symbol_relations (table, existing)** — source для graph loader.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Precision@20 на `graph_expansion.yaml` +20 п.п. над BFS (PPR 0.8 vs BFS 0.6).
- **SC-002**: PPR latency на 5k nodes ≤ 150 мс p95; на 50k nodes ≤ 1.5 с.
- **SC-003**: Convergence в ≤ 30 итерациях для 95% запросов (alpha=0.85).
- **SC-004**: Memory footprint на 50k nodes ≤ 200 MB (networkx граф).
- **SC-005**: Cache hit rate ≥ 70% при sustained load (большинство запросов — к одному графу в окне 5 мин).

## Assumptions

- `networkx>=3.2` достаточно для ≤50k nodes; `igraph` опционален для больших графов.
- `symbol_relations` уже существует (Phase 1 foundation).
- Eval harness (#6) используется для валидации SC-001.
- PPR-метрика симметрична для наших целей (undirected bridges учитываются через reverse edges опционально).
- Граф LV_DCP-монорепо на момент pilot ~3k nodes; full-scale testing через synthetic график.

## Dependencies & Constraints

- Зависит от: существующей `symbol_relations` таблицы (Phase 1).
- Блокеров по другим items нет.
- Желательно: #6 для валидации SC-001.
- Constitution §15 (graph-first retrieval) — прямое воплощение.
- ADR-001: PPR CPU-bound; запускается в worker или в backend async — не блокирует event loop.
