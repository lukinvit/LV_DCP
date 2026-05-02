# LV_DCP Idea Bank — банк идей из ресёрча популярных GitHub-проектов

**Дата:** 2026-05-02
**Источник:** глубокий ресёрч по 4 категориям (AI coding agents, code graphs / RAG, embeddings & retrieval, infra / Obsidian / MCP). Только репозитории с реальной популярностью (>1k stars) или признанные стандарты индустрии.

## Как читать этот документ

Каждая идея описана в формате:
- **Что это** — репозиторий и ссылка.
- **Что даёт нам простыми словами** — без жаргона.
- **Какую проблему решает** — привязка к нашим целям из ТЗ §7 (token reduction, retrieval quality, watch-loop reliability, edit safety, local-first).
- **Срок** — `S` (1–3 дня), `M` (1–2 недели), `L` (1–2 месяца), `XL` (квартал+).
- **Риски** — где можно споткнуться.

Идеи отсортированы по **приоритету внедрения**, а не по категориям. Если хочется по категориям — смотрите секцию «Карта по категориям» в конце.

---

## Раздел 1. Топ-10 быстрых побед (Must-have в Phase 1)

Эти десять идей закрывают 80% разрыва между текущим планом LV_DCP и SOTA-практиками 2026 года. Все либо `S`, либо `M`, и каждый даёт измеримый эффект.

### 1.1. MCP-сервер поверх retrieval API

- **Что это:** [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) (FastMCP), [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) — официальный SDK + ~70+ референсных серверов, индустриальный стандарт 2025–2026 (под Linux Foundation Agentic AI Foundation).
- **Что даёт:** ~200 строк кода — и LV_DCP видится **одновременно** в Claude Desktop, Claude Code, Cursor, Cline, Continue, Windsurf, JetBrains AI, ChatGPT (с марта 2025), Gemini, LangGraph, CrewAI. Один сервер — все клиенты.
- **Решает:** проблему дистрибуции. Без MCP мы изолированы — каждая интеграция пишется руками. С MCP пользователь говорит «у меня есть LV_DCP» и сразу подключает его к любому инструменту.
- **Срок:** **S** (2 дня). FastMCP с декораторами автоматически генерирует tool schemas из type hints.
- **Риски:** MCP-спецификация ещё развивается — пин на конкретную версию SDK. Auth в stdio-режиме отсутствует (для локального — ок).
- **Влияние:** **критическое**. Это самая высокая отдача за 2 дня работы во всём ресёрче.

### 1.2. PageRank repo-map от Aider

- **Что это:** алгоритм из [Aider-AI/aider](https://github.com/Aider-AI/aider) (~41k stars) — статья [aider.chat/docs/repomap.html](https://aider.chat/docs/repomap.html).
- **Что даёт:** автоматическое ранжирование «какие файлы важны для текущей задачи» на основе графа ссылок. Без LLM, без embeddings — работает мгновенно с холодного старта индекса. Aider публиковал замеры: дает накладывает edit-accuracy gain в разы по сравнению с наивной подачей файлов.
- **Решает:** **token reduction** на L0 (cold start) — даёт ranked context до того, как summaries и embeddings прогрелись. Это ровно то, чего нам не хватает в первые минуты работы с новым проектом.
- **Как работает (упрощённо):** tree-sitter извлекает определения и ссылки → строится directed graph «файл A ссылается на символ из файла B» → personalized PageRank с источниками = текущий файл и упомянутые символы → top-N в бюджете токенов с elided skeletons (только сигнатуры функций + строки со ссылками).
- **Срок:** **M** (1 неделя). NetworkX уже подразумевается в `libs/graph`. Один Python-файл.
- **Риски:** PageRank — глобальный сигнал, не учитывает семантику запроса. Нужен hybrid с vector. На больших монорепо (Aider — 60+ сек cold start) — но мы это смягчаем worker-индексацией.
- **Влияние:** **высокое**. Закрывает «первые 5 секунд» работы с проектом.

### 1.3. Hybrid search в Qdrant: dense + sparse в одной коллекции

- **Что это:** native sparse vectors в Qdrant 1.10+ через [Qdrant/bm25](https://huggingface.co/Qdrant/bm25) и [Qdrant/minicoil-v1](https://qdrant.tech/articles/minicoil/) + Query API с RRF/DBSF фьюжн.
- **Что даёт:** поиск по ключевым словам (BM25) и семантический (dense) — одной коллекцией, одним round-trip'ом. **miniCOIL** — это «BM25, который понимает контекст слова», особенно полезно для кода (camelCase, snake_case identifiers матчатся семантически).
- **Решает:** retrieval quality на коде. Dense embeddings плохо находят редкие идентификаторы (имя класса встречается 1–2 раза → embedding неинформативен), BM25 их находит. Hybrid выигрывает на каждом задаче.
- **Срок:** **M** (1 неделя). Named vectors `dense` + `sparse` в `devctx_chunks` и `devctx_symbols`. Соответствует ADR §27 («не множим коллекции»).
- **Риски:** нужна Qdrant 1.10+ (зафиксировать в `docker-compose`). Storage растёт на ~30%.
- **Альтернатива, которую отвергли:** внешний BM25 (Tantivy, pyserini, Postgres FTS) — нарушает modular monolith, два индекса синхронизировать.

### 1.4. voyage-code-3 как embedding по умолчанию

- **Что это:** [Voyage AI voyage-code-3](https://blog.voyageai.com/2024/12/04/voyage-code-3/) — SOTA для кода с декабря 2024 до сегодняшнего дня (май 2026).
- **Что даёт:** +13.8% к OpenAI v3-large, +16.8% к CodeSage-large на 32 code-retrieval датасетах. Контекст 32K токенов. Поддержка Matryoshka (256/512/1024/2048 dim) + int8/binary квантизации.
- **Решает:** retrieval quality на коде из коробки. Цена: $0.18 / 1M tokens; первые 200M токенов бесплатно — этого хватает на bootstrap проекта 5M токенов = $0.90 за полный re-embed.
- **Срок:** **S** (1–2 дня). Заменить адаптер `libs/embeddings/`, добавить `model_version="voyage-code-3@1024"` в payload.
- **Риски:** API-зависимость. Решение: всегда держим **локальный fallback** (см. 1.5).

### 1.5. Matryoshka truncation для cost-control

- **Что это:** [Matryoshka Representation Learning](https://huggingface.co/blog/matryoshka) — embeddings обучены так, что первые N измерений уже информативны.
- **Что даёт:** для `devctx_chunks` (где records миллионы) хранить **256-dim** вместо 1024-dim → ~80% экономии storage и 4× быстрее поиск, при потере 2–3% recall. Для `devctx_summaries` (мало записей) оставляем 1024-dim — там точность важнее.
- **Решает:** cost при росте проектов. Без Matryoshka мы либо платим 4× за storage, либо теряем качество.
- **Срок:** **S** (1 день). Truncate-and-renormalize — тривиальная операция в embedding-адаптере. Без re-embed.
- **Риски:** нет — сохраняем full vector, отдаём усечённый.

### 1.6. Watchman как опциональный backend для file watcher

- **Что это:** [facebook/watchman](https://github.com/facebook/watchman) (~13k stars) — продакшн-grade watcher, работает в Meta >10 лет. Python-клиент [pywatchman](https://pypi.org/project/pywatchman/) стал prod-stable в мае 2025.
- **Что даёт:** надёжность под нагрузкой. `watchdog` (наш текущий план) теряет события при `git checkout`, `npm install`, при просыпании Mac'а из sleep. Watchman переживает рестарты, имеет журнал FSEvents с recovery, и cookie/since-запросы — идеально для incremental scan.
- **Решает:** **watch-loop reliability** — главный болевой пункт desktop-агента в проде на macOS.
- **Срок:** **M** (1 неделя). Один файл `libs/watcher/backends/{watchman,watchdog}.py` за Protocol-интерфейсом. Watchdog оставляем fallback'ом на случай, если у пользователя нет `brew install watchman`.
- **Риски:** дополнительная зависимость для пользователя. Решение: lazy detection при старте агента.

### 1.7. Content-Defined Chunking (Rabin / FastCDC) от restic

- **Что это:** алгоритм из [restic/restic](https://github.com/restic/restic) (~28k stars). 64-байтное скользящее окно Rabin fingerprint → граница чанка при low-21-bits == 0 → ~1 MiB средний размер чанка.
- **Что даёт:** **chunk-стабильность при сдвигах**. Если в начале файла добавили строку — обычное line/size-based chunking сместит ВСЕ чанки и потребует re-embed всего файла. Rabin/FastCDC даёт сдвиго-стабильные границы — re-embed только изменённого чанка.
- **Решает:** dominant cost при едитинге — re-embedding неизменённого кода. Это самая большая экономия в pipeline после bootstrap.
- **Срок:** **M** (1–2 недели). Pure-Python Rabin chunker — ~150 LOC; либо обёртка над `fastcdc-rs` через PyO3.
- **Риски:** внутри одного проекта — никаких. Cross-project chunk reuse невозможен (рандомный полином на проект — это by design защита от watermark-атак).

### 1.8. Continue Custom Context Provider — HTTP-адаптер

- **Что это:** [continuedev/continue](https://github.com/continuedev/continue) поддерживает [HTTP context provider](https://docs.continue.dev/customize/custom-providers) — Continue POSTит в наш URL, мы отвечаем массивом `ContextItem`.
- **Что даёт:** интеграция с Continue **бесплатно** — без TypeScript-плагина. Один и тот же backend обслуживает MCP и Continue HTTP.
- **Решает:** покрытие IDE-пользователей до того, как у нас появится свой VS Code-плагин (Phase 3).
- **Срок:** **S** (1–2 дня). Один адаптер-роут `/continue/context` поверх существующих retrieval-эндпоинтов.
- **Риски:** нет; HTTP-путь официально поддерживается Continue.

### 1.9. uv workspaces + Astral toolchain

- **Что это:** [astral-sh/uv](https://github.com/astral-sh/uv) (~50k stars) workspaces — Cargo-style monorepo с одним lockfile и per-package `pyproject.toml`. [astral-sh/ruff](https://github.com/astral-sh/ruff) уже у нас. [astral-sh/ty](https://github.com/astral-sh/ty) — новый type-checker, 10–60× быстрее mypy/pyright.
- **Что даёт:** per-package versioning для `apps/agent`, `apps/backend`, `apps/cli`, `libs/*`. Резолв зависимостей один раз, CI быстрее.
- **Решает:** боль монорепо в Python. Без workspaces у нас либо один большой `pyproject.toml` (плохо для апгрейдов отдельных компонентов), либо отдельные lockfiles (рассинхрон).
- **Срок:** **S** (1 день). Добавить `[tool.uv.workspace] members = ["apps/*", "libs/*"]`.
- **Риски:** ty пока в beta (~53% typing spec). **Рекомендация:** mypy остаётся CI-gate'ом, ty добавляем как fast pre-commit/LSP в advisory режиме. Свопаем дефолт когда ty 1.0 со стабильной поддержкой Pydantic.

### 1.10. AGENTS.md + симлинк на CLAUDE.md

- **Что это:** [AGENTS.md spec](https://agents.md/) — индустриальный стандарт под Linux Foundation AAIF, поддержан Codex, Cursor, Amp, Jules, Factory, Goose, OpenHands.
- **Что даёт:** наш CLAUDE.md уже семантически совместим. Один симлинк или дубликат — и LV_DCP читается всеми не-Claude tooling.
- **Решает:** дистрибуция, lock-in. Без AGENTS.md мы зависим от Claude-only клиентов.
- **Срок:** **S** (1 час).
- **Риски:** нет.

---

## Раздел 2. Архитектурные ADR-решения (принять до Phase 2)

Эти идеи требуют ADR **сейчас**, иначе миграция позже станет XL. Реализация может ехать в Phase 2.

### 2.1. Temporal knowledge graph (модель Graphiti)

- **Что это:** [getzep/graphiti](https://github.com/getzep/graphiti) (~20k stars) — bi-temporal knowledge graph для агентов. Каждый факт имеет validity window («это было правдой между T1 и T2»). Supersession edges вместо delete.
- **Что даёт:** уникальная capability для git-aware queries: «покажи символы, которые были связаны до рефакторинга», «когда сломалась эта зависимость». Это **дифференциация LV_DCP vs Cursor/Cody** — никто из конкурентов этого не делает.
- **Решает:** retrieval quality на исторических вопросах. Без bi-temporal — full git replay при каждом запросе.
- **Срок:** **L** (1–2 месяца) на реализацию. **S** на ADR.
- **Почему ADR сейчас:** добавить временные интервалы в SQLAlchemy-модели **сейчас** = 0 миграций; сделать это через год = миграционный ад с переписыванием графа. Postgres `tstzrange` решает это нативно — Neo4j не нужен (нарушает «Postgres primary»).
- **Риски:** сложность запросов. Использовать только для `relations`-таблиц, не для `symbols`.

### 2.2. Event-sourced state + workspace abstraction (от OpenHands)

- **Что это:** [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) (~70k stars), [Software Agent SDK paper](https://arxiv.org/abs/2511.03690) (ноябрь 2025).
- **Что даёт:** event-sourced state с deterministic replay → можно проиграть edit-сессию обратно для аудита и багфикса. Workspace abstraction → desktop-агент и cloud worker имеют **один** SDK.
- **Решает:** edit safety (наш edit guard pipeline получает reproducibility «бесплатно»), упрощает Phase 3 (web/cloud agents).
- **Срок:** **L–XL** на полный рефакт. **S** на ADR + первичный SDK-сlauchecton.
- **Риски:** event sourcing накладывает overhead. Нужно решить ADR-уровнем, не задним числом.

### 2.3. SCIP как внутренний lingua franca для symbol IDs

- **Что это:** [sourcegraph/scip](https://github.com/sourcegraph/scip) — protobuf-схема code intelligence, наследник LSIF. Готовые индексеры: scip-python, scip-typescript, scip-java, scip-go, scip-clang, scip-ruby.
- **Что даёт:** стабильные кросс-языковые symbol IDs (`scheme manager package version descriptor`) как естественный primary key для `symbols.scip_symbol_id`. Готовые индексеры → быстрый bootstrap для популярных языков без писать парсеры с нуля.
- **Решает:** ускорение Phase 1, совместимость с экосистемой (Sourcegraph, GitHub Code Search).
- **Срок:** **M** (на адаптер потребления готовых индексеров). **L** — для собственных языков пишем SCIP-совместимый superset.
- **Риски:** SCIP-индексеры — отдельные binaries per language; их жизненный цикл управляет desktop-агент. Размер индексов на больших репо.
- **Что НЕ делать:** не заставлять весь pipeline через SCIP-only. У нас уже tree-sitter + (планируется) stack-graphs. SCIP — exchange-format, не внутренняя репрезентация.

### 2.4. Stack-graphs для cross-file name resolution

- **Что это:** [github/stack-graphs](https://github.com/github/stack-graphs) (~700 stars, GitHub-maintained). File-isolated подграфы → idempotent кэш + path-finding для resolve.
- **Что даёт:** правильные «definition / reference» links через файлы **без полного билда проекта**. Tree-sitter сам по себе не делает name resolution — он только AST. Stack-graphs закрывает дыру.
- **Решает:** граф-этап retrieval — call/import/inherit edges становятся precise, а не приближение.
- **Срок:** **L** (1–2 месяца). Привязка через subprocess CLI с кэшем content-хэшей. Готовые TSG для Python/JS/TS/Java; для других языков — недели на собственные TSG-rules.
- **Риски:** Rust core; в Python — через subprocess или PyO3. Subprocess проще, но добавляет overhead.

### 2.5. Skeleton-chunking от LlamaIndex CodeHierarchyNodeParser

- **Что это:** [llama-index-packs-code-hierarchy](https://github.com/run-llama/llama_index/tree/main/llama-index-packs/llama-index-packs-code-hierarchy) — режет файл по scope tree-sitter; **тело длинной функции компрессируется в summary + ссылку на полный текст**.
- **Что даёт:** chunking для embedding по семантическим границам (функция, класс, модуль) вместо линий. Длинные функции эмбеддятся как «сигнатура + summary», полное тело подгружается только когда модель просит raw.
- **Решает:** retrieval quality для embedding. Большая функция, размазанная по 5 чанкам — теряет связность; одна функция = один чанк = один смысл.
- **Срок:** **S** (взять алгоритм). **M** (если интегрировать пакет целиком).
- **Риски:** llama_index — heavy framework. Лучше скопировать алгоритм skeleton-replacement в `libs/parsers`, не тащить SDK.

---

## Раздел 3. Качество retrieval (Phase 2)

### 3.1. Reranker: Cohere/Voyage в проде, BGE локально

- **Что это:** [Cohere Rerank 3.5](https://cohere.com/blog/rerank-3pt5), [Voyage rerank-2](https://blog.voyageai.com/2024/09/30/rerank-2/) — API; [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) — локальный.
- **Что даёт:** финальный stage `top-50 → top-10` перед отдачей в Claude. Voyage rerank-2 даёт +13.89% к OpenAI v3-large на code retrieval.
- **Решает:** retrieval quality на финальной стадии — без reranker'а top-10 dense часто содержит «соседей по коду», но не самое релевантное.
- **Срок:** **S** (1–2 дня). API-вызов в pipeline.
- **Риски:** latency ~600ms p50. Для context pack приемлемо. Для completion — нет.

### 3.2. ColBERT late-interaction как middle-stage rerank

- **Что это:** [stanford-futuredata/ColBERT](https://github.com/stanford-futuredata/ColBERT), [AnswerDotAI/RAGatouille](https://github.com/AnswerDotAI/RAGatouille). Native поддержка в Qdrant 1.10+ через multi-vector named vectors.
- **Что даёт:** token-level matching для symbol search — особенно полезно для function signatures и type signatures, где token-level важнее семантики целого блока.
- **Решает:** quality middle-stage `top-200 → top-50`. ColBERT даёт +5–10% NDCG vs single-vector dense.
- **Срок:** **M**. Multi-vector schema в Qdrant + storage budget (×N токенов на документ).
- **Риски:** storage растёт ×N. Использовать только для `devctx_symbols` и `devctx_patterns` (короткие документы, мало записей), **не** для `devctx_chunks`.
- **Когда включать:** после того как eval (RAGAS) покажет, что cross-encoder rerank — bottleneck.

### 3.3. RAGAS + CoIR как eval contract (ADR-002)

- **Что это:** [explodinggradients/ragas](https://github.com/explodinggradients/ragas) — метрики faithfulness, context-precision, context-recall. [CoIR-team/coir](https://github.com/CoIR-team/coir) — стандартный benchmark для code retrieval (ACL 2025).
- **Что даёт:** retrieval quality как контракт — любая смена embedding/reranker/chunking пробегает eval, gate в CI.
- **Решает:** ADR-002 без этого не выполняется. Без eval — нет gate качества.
- **Срок:** **M** (1–2 недели). Минимум CoIR subset + 1–2 кастомных датасета на собственных проектах.
- **Риски:** нет; стандартная практика.

### 3.4. NL-augmented chunks (паттерн от Qodo)

- **Что это:** перед эмбеддингом каждый chunk обогащается LLM-сгенерированным natural-language description. Эмбеддится не сырой код, а `code + summary`.
- **Что даёт:** embedding модели обучены на NL-data; сырой код — не их сильная сторона. NL-обёртка повышает retrieval quality на NL-запросах.
- **Решает:** quality для запросов вида «как работает аутентификация» — где ключевые слова не встречаются в коде дословно.
- **Срок:** **M**. Один LLM-pass на чанк при индексации; кэш по content-hash.
- **Риски:** стоимость bootstrap (один LLM call на чанк × миллионы). Решение: только для `importance >= medium` чанков.

### 3.5. GraphRAG community summaries (адаптация для кода)

- **Что это:** [microsoft/graphrag](https://github.com/microsoft/graphrag) (~22k stars) — Leiden community detection поверх entity graph + иерархические LLM-summaries для каждой community.
- **Что даёт:** автоматические «темы проекта» — auth flow, embedding subsystem, watcher daemon. Это subsystem-level summaries сверх module-summaries.
- **Решает:** retrieval quality для high-level вопросов («как работает sync?», «обзор архитектуры»). Без community-слоя — модель видит файлы, но не подсистемы.
- **Срок:** **L**. Leiden поверх нашего graph (NetworkX/igraph), LLM-summary каждой community в `devctx_summaries` с payload `entity_type=community, level=N`.
- **Риски:** стандартный GraphRAG entity-extraction prompt подходит для docs, не для кода. Нужен code-specific prompt: «summarize what this cluster of related symbols does, name 3–5 capabilities, list edge symbols to other clusters».
- **Что НЕ делать:** не тащить microsoft/graphrag целиком (тяжёлый dataframe pipeline). Скопировать алгоритм.

---

## Раздел 4. Operational hardening (Phase 1–2)

### 4.1. Cursor-style Merkle tree для desktop-agent ↔ backend sync

- **Что это:** документированная техника Cursor — иерархическое дерево хешей по файлам и папкам, sync только по diverging branches.
- **Что даёт:** один запрос «изменилось ли что-то в `libs/retrieval`?» возвращает yes/no через сравнение одного хеша. Bandwidth-efficient.
- **Решает:** watch-loop reliability — резервный механизм reconciliation на случай пропущенных FSEvents.
- **Срок:** **S** (несколько дней). Поверх существующего content-hash подхода.
- **Риски:** нет; чистый win.

### 4.2. aiomonitor + aiojobs для desktop-агента

- **Что это:** [aio-libs/aiomonitor](https://github.com/aio-libs/aiomonitor) — telnet REPL в живой asyncio loop. [aio-libs/aiojobs](https://github.com/aio-libs/aiojobs) — graceful shutdown пулов.
- **Что даёт:** debug daemon в проде в 3 ночи без рестарта. Mid-flight scan/embedding не убиваются на launchd-restart.
- **Решает:** operability — критично для launchd-managed daemon.
- **Срок:** **S** (~10 LOC).
- **Риски:** bind на localhost only, gate за dev-flag.

### 4.3. launchd plist best-practices

- **Что это:** не репозиторий, а собранные best-practices ([launchd.info](https://www.launchd.info/)).
- **Что даёт:** правильный шаблон plist'а: `KeepAlive={SuccessfulExit=false}`, `ThrottleInterval=30`, `ProcessType=Background`, `LowPriorityIO=true`, логи в `~/Library/Logs/lvdcp/`. Секреты — из Keychain, не из EnvironmentVariables.
- **Решает:** crash-loop hammering, конфликт со Spotlight/Time Machine, потеря логов.
- **Срок:** **S** (один Jinja-шаблон в `deploy/launchd/`).
- **Риски:** macOS 13+ требует Full Disk Access — задокументировать в onboarding.

### 4.4. Auto-compact threshold (паттерн от Cline/Roo-Code)

- **Что это:** [cline/cline](https://github.com/cline/cline) auto-compacts context на 80% заполнения. [RooCodeInc/Roo-Code](https://github.com/RooCodeInc/Roo-Code) — intelligent condensing by default (3.19).
- **Что даёт:** наш context pack мониторит заполнение и инициирует summary-rollup до переполнения. Никаких truncation-сюрпризов в проде.
- **Решает:** edit safety — context overflow ломает сессии непредсказуемо.
- **Срок:** **S** (логика в context-pack assembler).
- **Риски:** нет.

### 4.5. Content-hash cache + lineage (паттерн от cocoindex)

- **Что это:** [cocoindex-io/cocoindex](https://github.com/cocoindex-io/cocoindex) (~1.5k stars) — incremental data-flow framework. Lineage tracking-table в Postgres (file → chunks → embeddings).
- **Что даёт:** референс-схема для нашего worker pipeline: что переэмбеддить, когда изменился родительский summary, как откатить partial-update.
- **Решает:** ровно нашу incremental-by-default дисциплину (ТЗ §7).
- **Срок:** **S** (на чтение). **M** (адаптация схемы tracking-таблиц).
- **Риски:** нет; берём идею, не код.

---

## Раздел 5. Phase 2–3 (планомерные улучшения)

### 5.1. Claude Code plugin с hooks

- **Что это:** Claude Code plugin ecosystem ([awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code), ~5k stars). Hooks: `PreToolUse`, `PostToolUse`, `SessionStart`, `UserPromptSubmit`, 12 lifecycle events. Async hooks + HTTP hooks стабильны с января 2026.
- **Что даёт:**
  - `SessionStart` → bootstrap `.context/` если не существует;
  - `PreToolUse` (matchers `Read|Grep|Glob`) → автоматически вызывает `lvdcp_pack` и инжектит в контекст;
  - `PostToolUse` (matcher `Edit|Write`) → инвалидирует затронутые summaries server-side;
  - `UserPromptSubmit` → обогащает promp релевантным паком.
- **Решает:** превращает `BLOCKING REQUIREMENT` из CLAUDE.md (текст, который модель может проигнорировать) в enforced behavior харнесса.
- **Срок:** **S–M** (Phase 2). Один репо `claude-code-lvdcp` с `hooks/`, `skills/`, `commands/`. Публикуется в awesome-claude-code.
- **Риски:** Claude Code plugin API ещё развивается — пин на documented release.

### 5.2. Continue + VS Code extension

- **Что это:** [continuedev/continue](https://github.com/continuedev/continue) (~25k stars) Custom Context Provider TypeScript API.
- **Что даёт:** глубокая VS Code-интеграция (sidebar, autocomplete, agent mode) поверх нашего retrieval API.
- **Решает:** IDE UX, который MCP не выражает (gutter markers, code lens, inline lenses).
- **Срок:** **L** (1–2 месяца). Phase 3.
- **Риски:** TypeScript surface to maintain. Mitigate: LSP-server в Python (`pygls`), TS-extension — тонкий клиент.

### 5.3. Quartz для публикации Obsidian vault

- **Что это:** [jackyzha0/quartz](https://github.com/jackyzha0/quartz) (~10.9k stars) — markdown→static-site, понимает wikilinks и frontmatter.
- **Что даёт:** publish read-only KB на GitHub Pages / любой статичный хост.
- **Решает:** «KB для людей, которые не используют Obsidian».
- **Срок:** **S** (point Quartz at vault folder).
- **Риски:** Node.js build dep — приемлемо для publish-step.

### 5.4. Dataview-friendly frontmatter (вместо собственного Obsidian-плагина)

- **Что это:** конвенция frontmatter совместимая с [blacksmithgu/obsidian-dataview](https://github.com/blacksmithgu/obsidian-dataview) (~9k stars).
- **Что даёт:** users пишут DQL-запросы и live tables к нашему KB без нашего кода. Двусторонняя связь — через стандартный плагин Obsidian.
- **Решает:** «как сделать KB интерактивной» без TypeScript-плагина.
- **Срок:** **S** (frontmatter convention в `libs/obsidian`).
- **Риски:** Dataview — community-maintained, но de-facto стандарт.
- **Решение по Obsidian-плагину:** **не писать**. Plain Markdown + Dataview frontmatter + Quartz publish покрывает 95% потребностей. Плагин только если потребуется реалтайм-bidirectional edit.

### 5.5. Sub-agents паттерн от Claude Code

- **Что это:** Claude Code [anthropics/claude-code](https://github.com/anthropics/claude-code) (~119k stars) — задача делегируется специализированному агенту со своим context budget.
- **Что даёт:** наш CLI и edit-pipeline делегируют subtasks (parsing, summarization, eval) изолированным агентам — каждый со своим budget.
- **Решает:** edit safety — основной агент не загрязняет context промежуточными результатами.
- **Срок:** **M**. Уже неявно есть через наши `agents/*.md` (fastapi-architect, db-expert, etc).
- **Риски:** нет.

### 5.6. ast-grep как pre-edit guard

- **Что это:** [ast-grep/ast-grep](https://github.com/ast-grep/ast-grep) (~13.6k stars) — structural pattern matching поверх tree-sitter, быстрее semgrep.
- **Что даёт:** structural search «найди все вызовы `db.execute` с raw SQL»; impact-analysis детектор паттернов перед edit'ом; refactor preview.
- **Решает:** edit safety (ТЗ §16–17 — pre-edit guard).
- **Срок:** **S** для CLI integration (subprocess); **M** для embedded.
- **Риски:** Rust binary; subprocess overhead. Использовать в worker, не в request path.

### 5.7. semgrep для privacy/security policies

- **Что это:** [semgrep/semgrep](https://github.com/semgrep/semgrep) (~10k+ stars) — rule engine с 3000+ community rules.
- **Что даёт:** детектит секреты и dangerous patterns перед индексированием. «Этот файл содержит API-ключ → privacy_mode=restricted».
- **Решает:** privacy policies в `libs/policies`.
- **Срок:** **S** как внешний инструмент, **M** как библиотека правил.
- **Риски:** Pro-фичи (taint-mode inter-procedural) платные. Community rules покрывают basic.

### 5.8. Mode-based personas (от Roo-Code)

- **Что это:** Roo-Code multi-mode personas (Architect / Code / Debug) с разным system prompt и tools.
- **Что даёт:** наш `mode` параметр в `lvdcp_pack` расширяется на 4–5 пресетов с разным retrieval mix (`navigate`, `edit`, `debug`, `architect`, `review`).
- **Решает:** edit safety + token reduction — правильный контекст для типа задачи.
- **Срок:** **S–M**. У нас уже есть mode параметр.
- **Риски:** дрейф mode-prompts; нужны eval-тесты per mode (см. 3.3).

---

## Раздел 6. Watch list (мониторим, не внедряем)

### 6.1. lancedb/lancedb

- Versioned vector DB на Rust + columnar Lance format. Идеален для embedded/local-first.
- **Когда рассматривать:** если SQLite в `apps/agent` упрётся в потолок при offline retrieval. Сейчас — не критично.

### 6.2. pgvector + ParadeDB

- Vector + BM25 в Postgres (один движок).
- **Не рассматриваем:** Qdrant зафиксирован constitution'ом и ADR. Pgvector проигрывает по QPS на 50M+ vectors. Релевантно только для проектов <5M chunks.

### 6.3. TabbyML/tabby

- Self-hosted Copilot. Tree-sitter tags + adaptive caching.
- **Когда:** если LV_DCP пойдёт в enterprise сегмент. Не приоритет фазы 1–2.

### 6.4. voideditor/void

- Open-source Cursor-альтернатива. **Развитие приостановлено** — команда переключилась на «novel coding ideas».
- **Не интегрируем:** проект paused. Watch as reference (Gather mode vs Agent mode = clean separation read-only vs write).

### 6.5. bloop-ai/bloop

- Tantivy + Qdrant + RRF + tree-sitter в Rust. Замедлилось.
- **Использование:** референс гибридной архитектуры. Code не переносим (Rust).

### 6.6. block/goose, OpenHands microagents

- Goose — MCP-first агент. OpenHands V1 SDK — workspace abstraction.
- **Когда:** при пересмотре desktop-agent SDK. Сейчас — берём идеи (event-sourcing, microagents) в ADR.

### 6.7. eclipse-lsp4j / LSP servers (pyright, gopls, rust-analyzer)

- Universal source-of-truth для definitions/references/hover/diagnostics.
- **Когда:** opportunistic enrichment если у пользователя уже стоит LSP — дёргаем его вместо своего парсера. Phase 3.

### 6.8. yamadashy/repomix, gitingest, code2prompt

- Repo-pack-в-один-файл для LLM. ~25k+ stars (repomix).
- **Использование:** референс формата context pack. Дальше нашего ranked retrieval не идут.

### 6.9. silverbulletmd, dendronhq/dendron

- Dendron — архивирован. SilverBullet — нишевый.
- **Не рассматриваем.**

### 6.10. pinecone-io/canopy

- Архивирован. Pinecone сами рекомендуют Pinecone Assistant.
- **Не рассматриваем.**

---

## Раздел 7. Карта по категориям (для cross-reference)

### Code intelligence + AI agents
1.2 Aider PageRank · 4.4 Cline auto-compact · 5.1 Claude Code plugin · 5.5 Sub-agents · 5.8 Roo modes · 2.2 OpenHands SDK · 2.1 Graphiti · 6.5 Bloop · 6.4 Void

### Code graphs + RAG-for-code
2.3 SCIP · 2.4 Stack-graphs · 2.5 Skeleton-chunking · 3.5 GraphRAG communities · 5.6 ast-grep · 5.7 semgrep · 4.5 cocoindex · 6.7 LSP servers · 6.8 repomix

### Embeddings + retrieval
1.4 voyage-code-3 · 1.5 Matryoshka · 1.3 Hybrid Qdrant sparse · 3.1 Cohere/Voyage rerank · 3.2 ColBERT multi-vector · 3.4 NL-augmented chunks · 6.2 pgvector

### Infra / watchers / Obsidian / MCP
1.1 MCP server · 1.6 Watchman · 1.7 Rabin CDC · 1.8 Continue HTTP · 1.9 uv workspaces · 1.10 AGENTS.md · 4.1 Merkle sync · 4.2 aiomonitor · 4.3 launchd · 5.2 VS Code · 5.3 Quartz · 5.4 Dataview frontmatter · 6.1 LanceDB · 6.3 Tabby

---

## Раздел 8. Сводная таблица по приоритетам и срокам

| # | Идея | Срок | Приоритет | Решает |
|---|------|------|-----------|--------|
| 1.1 | MCP server | S | **Phase 1** | Дистрибуция в Claude/Cursor/Cline/Continue/ChatGPT |
| 1.2 | Aider PageRank | M | **Phase 1** | Cold-start ranked context |
| 1.3 | Hybrid sparse+dense Qdrant | M | **Phase 1** | Retrieval quality на коде |
| 1.4 | voyage-code-3 default | S | **Phase 1** | SOTA embedding для кода |
| 1.5 | Matryoshka 256-dim | S | **Phase 1** | 80% storage savings |
| 1.6 | Watchman backend | M | **Phase 1** | macOS watch reliability |
| 1.7 | Rabin/FastCDC chunking | M | **Phase 1** | Re-embed cost при edits |
| 1.8 | Continue HTTP provider | S | **Phase 1** | IDE coverage без TS-плагина |
| 1.9 | uv workspaces + ty | S | **Phase 1** | Monorepo + fast typecheck |
| 1.10 | AGENTS.md симлинк | S | **Phase 1** | Совместимость с не-Claude tooling |
| 2.1 | Temporal graph (ADR) | S→L | **Phase 1 ADR** | Git-aware queries (дифференциация) |
| 2.2 | Event-sourced (ADR) | S→XL | **Phase 1 ADR** | Replay edit-сессий |
| 2.3 | SCIP exchange format | M | **Phase 2** | Готовые индексеры для языков |
| 2.4 | Stack-graphs | L | **Phase 2** | Cross-file name resolution |
| 2.5 | Skeleton-chunking | S | **Phase 2** | Embedding по семантическим границам |
| 3.1 | Cohere/Voyage rerank | S | **Phase 2** | Финальный rerank pack |
| 3.2 | ColBERT middle-stage | M | **Phase 2** | Symbol-level rerank |
| 3.3 | RAGAS + CoIR eval | M | **Phase 1** | ADR-002 contract |
| 3.4 | NL-augmented chunks | M | **Phase 2** | Quality на NL-запросах |
| 3.5 | GraphRAG communities | L | **Phase 2** | Subsystem-level summaries |
| 4.1 | Merkle tree sync | S | **Phase 1** | Reconciliation резерв |
| 4.2 | aiomonitor + aiojobs | S | **Phase 1** | Operability daemon |
| 4.3 | launchd best-practices | S | **Phase 1** | Daemon stability |
| 4.4 | Auto-compact threshold | S | **Phase 2** | Context overflow safety |
| 4.5 | cocoindex lineage схема | M | **Phase 2** | Incremental tracking |
| 5.1 | Claude Code plugin | S–M | **Phase 2** | Enforced LV_DCP discipline |
| 5.2 | VS Code extension | L | **Phase 3** | IDE-specific UX |
| 5.3 | Quartz publish | S | **Phase 2** | KB для не-Obsidian users |
| 5.4 | Dataview frontmatter | S | **Phase 1** | Two-way binding с Obsidian |
| 5.5 | Sub-agents паттерн | M | **Phase 2** | Edit safety |
| 5.6 | ast-grep guard | S | **Phase 2** | Pre-edit pattern match |
| 5.7 | semgrep policies | S | **Phase 2** | Privacy/security rules |
| 5.8 | Mode-based personas | S–M | **Phase 2** | Pack composition по intent |

---

## Раздел 9. Что менять в существующих документах после этого банка

Если решим внедрять — потребуется пересмотр:
- **ADR-новый** на temporal graph модель (раздел 2.1) — до Phase 2.
- **ADR-новый** на event-sourced state + workspace abstraction (2.2) — до Phase 2.
- **ADR-002** дополняется CoIR + RAGAS как concrete eval datasets (3.3).
- **constitution.md** — добавить MCP как mandatory integration surface (1.1).
- **CLAUDE.md** — секция «Discipline» заменяется на ссылку на Claude Code plugin (5.1).
- **deploy/docker-compose** — pin Qdrant 1.10+ (1.3); добавить TEI/Infinity сервис для self-host embeddings/rerankers (см. отчёт по embeddings).
- **deploy/launchd** — Jinja-шаблон plist'а (4.3).

---

## Источники

Каждая идея в этом документе ссылается на конкретный репозиторий или статью. Полный список проверенных источников по 4 категориям ресёрча — см. summary в `docs/research/raw/` (если будем сохранять полные отчёты), либо по ссылкам прямо в тексте идей.

Принципы отбора:
- Только репозитории с >1k stars **или** признанные стандарты индустрии (SCIP, MCP, AGENTS.md).
- Только активные проекты на момент мая 2026 (исключения помечены в Watch list).
- Числа звёзд — приближённые, обозначены `~`.
- Каждая идея проверена на совместимость с фиксированным стеком LV_DCP (Python 3.12 async, FastAPI, SQLAlchemy 2 async, Qdrant фиксированные коллекции + payload isolation, Postgres 16, Dramatiq/RQ, modular monolith).
