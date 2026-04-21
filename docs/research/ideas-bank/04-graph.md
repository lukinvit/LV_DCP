# Graph: code relations, communities, temporal

5 идей по графовому слою — что хранить, как расширять, как обогащать историей.

---

## 1. Personalized PageRank для graph expansion

- **Что даёт:** вместо BFS по N хопам — PPR с seed-нодами из query-символов. Важные callers/callees всплывают наверх, случайные связи отсеиваются. Рёбрам `calls` > `imports` > `references` задаются разные веса.
- **Проблема:** BFS по 2 хопам на графе среднего размера возвращает 200+ символов, большинство — мусор. LLM пожирает токены впустую.
- **Где:** `libs/retrieval/graph_expand.py`, `libs/graph/ppr.py`.
- **Влияние:** **H** — качественно меняет состав pack при вопросах про символы.
- **Срок:** **2–3 дня** (networkx даёт PPR out-of-the-box).
- **Источник:** HippoRAG (OSU-NLP-Group), Aider repo-map.

---

## 2. Leiden communities + community reports

- **Что даёт:** алгоритм Leiden выделяет кластеры плотно связанных символов — это архитектурные подсистемы, не всегда совпадающие с директориями. Для каждой community LLM генерит «community report» (summary уровня подсистемы).
- **Проблема:** между «module summary» и «project summary» зияет дыра для больших проектов. Communities — естественный средний уровень. Плюс закрывает `mode="overview"` в pack-API.
- **Где:** `libs/graph/communities.py`, `libs/summaries/community_report.py`.
- **Влияние:** **M-H** — новый уровень иерархии summaries, нужен для global search.
- **Срок:** **1–2 недели** (graspologic/igraph для Leiden, LLM-генерация reports).
- **Источник:** Microsoft GraphRAG.

---

## 3. Temporal edges + episodes (Graphiti-pattern)

- **Что даёт:** рёбра графа несут `valid_from` / `valid_to`. «Функция X вызывала Y до коммита abc123, после — Z». Episode = коммит = контейнер связанных изменений графа.
- **Проблема:** сейчас мы видим только snapshot текущего кода. Нет ответа на вопрос «откуда взялась эта связь», нет git-aware ranking (свежее важнее).
- **Где:** миграция Alembic + `libs/graph/models.py`, `libs/gitintel/episodes.py`.
- **Влияние:** **M** — разблокирует gitintel-фичи и pattern mining.
- **Срок:** **1 неделя**.
- **Источник:** Zep / Graphiti (getzep).

---

## 4. SCIP precise layer (scip-python)

- **Что даёт:** Protobuf-формат precise index от Sourcegraph. Точные символы и references (а не приблизительные tree-sitter). scip-python работает инкрементально, даёт monikers для cross-repo ссылок.
- **Проблема:** tree-sitter — быстрый approximation. Для refactor-safe edits (фаза 2) нужны точные references — иначе rename ломает код.
- **Где:** новый `libs/parsers/scip/`, backend-сервис или subprocess.
- **Влияние:** **H** для фазы 2 (edit safety); **M** для retrieval precision символов.
- **Срок:** **1–2 недели** (scip-python как external binary + парсер output).
- **Источник:** sourcegraph/scip, Sourcegraph Cody dual-layer (SCIP + embeddings).

---

## 5. MCP memory-server schema alignment

- **Что даёт:** Anthropic reference memory-server использует схему `entities / relations / observations`. Если наш граф совместим 1-в-1, получаем бесплатную совместимость с клиентами MCP.
- **Проблема:** наша текущая schema графа разрабатывалась в изоляции; выровнять её с MCP memory дёшево и открывает экосистему.
- **Где:** `libs/graph/schema.py`.
- **Влияние:** **M** — интероп.
- **Срок:** **1–2 дня**.
- **Источник:** modelcontextprotocol/servers (memory).

---

## Бонусные идеи (honorable mentions)

- **Claims extraction** (GraphRAG) — кроме relations, фиксируем утверждения («this function handles auth»). Полезно для pattern mining.
- **Dual-level query decomposition** (LightRAG) — query раскладывается на «какие сущности» + «какие связи/темы», два параллельных поиска, merge.
- **Gleaning loop** (nano-graphrag) — повторный вопрос к LLM «есть ли ещё сущности?» до stop. +30–50% recall при entity extraction. 1–2 дня.
- **Stack-graphs** (github/stack-graphs) — инкрементальный name resolution на scope-стеках. Мощно, но 2+ недель интеграции; дождаться фазы 2.

## Что НЕ делать в графе

- **Neo4j** как обязательная зависимость — ТЗ прямо запрещает. Остаёмся на Postgres с edges-table + networkx в памяти для PPR.
- **Полный импорт cognee** — берём ontology-идею, но не фреймворк.
- **Семантические triplets через LLM на каждом коммите** — дорого, без amortization. Только offline, раз за revision.
