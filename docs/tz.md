# Техническое задание
## Developer Context Platform для macOS + VS Code + Claude + Obsidian + локальный/удалённый RAG

**Версия:** 1.0  
**Статус:** Production-ready blueprint  
**Цель документа:** дать подробное, обоснованное ТЗ на систему, которая автоматически индексирует локальные проекты на macOS, уменьшает расход токенов при работе с Claude/агентами, публикует человекочитаемую knowledge base в Obsidian и остаётся лёгкой в эксплуатации.

---

# 1. Executive summary

Нужно спроектировать и реализовать **личную платформу инженерной памяти** для разработки, а не просто RAG по исходникам.

Платформа должна:
- автоматически находить проекты на Mac;
- следить за изменениями файлов;
- делать инкрементальный рескан;
- разбирать код структурно, а не как сплошной текст;
- строить summaries, граф связей, symbol index, architecture notes;
- сохранять embeddings и метаданные;
- собирать **context packs** для Claude/агентов вместо повторной загрузки всей codebase;
- синхронизировать knowledge base в Obsidian;
- поддерживать работу через CLI, local API, VS Code и Claude workflow;
- иметь нормальную эксплуатацию: очереди, healthchecks, retry, snapshots, наблюдаемость.

Ключевой принцип:

> Не читать весь код заново. Сначала работать по summaries, symbols, relations и recent changes. Raw code подтягивать только точечно.

---

# 2. Почему обычный RAG недостаточен

Если сделать только embeddings по чанкам файлов, возникнут системные проблемы:

1. **Потеря структуры.**
   Код — это не просто текст. Нужны символы, импорты, роуты, сервисы, конфиги, зависимости.

2. **Слабая точность на вопросах уровня архитектуры.**
   Вопросы типа «где живёт refresh token flow?» или «что затрагивает billing webhook?» плохо решаются голыми чанками.

3. **Высокая стоимость поддержки индекса.**
   Полный re-embed при любом изменении дорогой и бессмысленный.

4. **Плохая explainability.**
   Агенту нужно объяснить, *почему* найден именно этот файл/символ/модуль.

Поэтому нужна гибридная платформа:
- **structural index**;
- **semantic retrieval**;
- **graph relations**;
- **git-aware enrichment**;
- **context pack assembly**.

---

# 3. Цели проекта

## 3.1 Бизнес-цели
- Снизить расход токенов на повторное чтение проектов.
- Ускорить онбординг в старые и новые репозитории.
- Снизить время на архитектурную навигацию.
- Сделать reusable memory по всем проектам.
- Дать единый слой контекста для Claude, CLI, VS Code и Obsidian.

## 3.2 Технические цели
- Автоматический инкрементальный индекс без ручного запуска.
- Высокая точность retrieval в пределах проекта и между проектами.
- Контролируемая и безопасная синхронизация на сервер.
- Поддержка многоязычных codebases.
- Возможность расширения через hooks, subagents, MCP, Obsidian и future plugins.

## 3.3 UX-цели
- Минимум ручной конфигурации.
- Подключение нового проекта «из коробки».
- Понятный CLI.
- Человеческие markdown-артефакты.
- Возможность жить без тяжёлой UI-панели.

---

# 4. Non-goals

На старте **не** требуется:
- полноценный SaaS multi-user продукт;
- Kubernetes;
- тяжёлая графовая БД уровня Neo4j как обязательный компонент;
- полный rewrite всех IDE integrations;
- автогенерация production-кода без human review;
- идеальная семантика на 100% всех языков с первого дня.

---

# 5. Основные сценарии использования

## 5.1 Навигация по текущему проекту
Примеры запросов:
- Где обновляется access token?
- Какие файлы участвуют в webhook retry?
- Где описан жизненный цикл заказа?
- Какие изменения за последние 3 дня могли затронуть auth?

## 5.2 Межпроектный поиск
Примеры запросов:
- Где я уже делал refresh token logic?
- В каком проекте есть похожий Docker Compose?
- Где у меня уже использовался Qdrant / Redis / Ollama?

## 5.3 Генерация context pack для Claude
Пользователь вызывает команду, получает компактный markdown-блок и вставляет его в IDE/Claude вместо прогрузки половины репозитория.

## 5.4 Obsidian knowledge base
Для каждого проекта автоматически ведутся:
- overview;
- architecture;
- modules;
- flows;
- integrations;
- recent changes;
- tech debt;
- open questions.

## 5.5 Быстрый старт нового проекта
Платформа видит новый git-репозиторий, подключает его, применяет дефолтный профиль, делает initial deep scan и сразу генерирует `.context/` и markdown wiki.

---

# 6. High-level архитектура

```text
macOS Desktop Agent
 ├─ Project Discovery
 ├─ File Watcher
 ├─ Incremental Scan Scheduler
 ├─ Local Cache
 ├─ Obsidian Sync
 ├─ CLI
 └─ Local API / prompt bridge

Backend
 ├─ Retrieval API
 ├─ Metadata DB
 ├─ Vector DB integration
 ├─ Graph projection
 ├─ Job Queue
 ├─ Context Pack Builder
 ├─ Policy Engine
 └─ Admin / health endpoints

Workers
 ├─ Parsing pipeline
 ├─ Summarization pipeline
 ├─ Embedding pipeline
 ├─ Git intelligence pipeline
 └─ Publishing pipeline

Integrations
 ├─ Claude Code / CLAUDE.md / hooks / subagents
 ├─ VS Code
 ├─ Obsidian
 ├─ Git
 └─ Optional local model endpoints
```

---

# 7. Архитектурные принципы

## 7.1 Graph-first, summary-first, raw-last
Порядок retrieval всегда такой:
1. project/module summaries;
2. symbol candidates;
3. graph expansion;
4. semantic retrieval;
5. rerank;
6. точечные raw snippets.

## 7.2 Incremental by default
Система должна пересчитывать **только изменившееся и связанное**, а не весь проект.

## 7.3 Local-first, remote-assisted
Локальный агент отвечает за доступ к файловой системе и первичный контроль. Сервер — за долговременное хранение, retrieval и тяжёлые пайплайны.

## 7.4 Modular monolith
На серверной стороне — не микросервисы, а хорошо разрезанный modular monolith + workers.

## 7.5 Deterministic automation around LLM
LLM используется там, где нужен synthesis. Но критические шаги — watcher, hashing, parsing, relations, policies — должны быть детерминированными.

---

# 8. Состав решения

# 8.1 Desktop Agent (macOS)

## Назначение
Локальный сервис, работающий как демон через `launchd`, отвечающий за:
- обнаружение проектов;
- слежение за файловой системой;
- постановку scan jobs;
- локальный кэш;
- генерацию `.context/` файлов;
- синхронизацию в backend;
- синхронизацию в Obsidian.

## Требования
- запускаться автоматически;
- иметь pause/resume;
- уметь работать оффлайн и отправлять накопленные изменения позже;
- переживать перезапуск системы;
- не перегружать CPU при массовых изменениях;
- иметь `doctor` и health reporting.

## Технологии
- Python 3.12;
- FSEvents adapter / watchdog;
- Typer;
- SQLite local cache;
- httpx;
- pydantic settings.

---

# 8.2 Project Discovery & Registry

## Назначение
Управление рабочими пространствами, проектами и их политиками.

## Функции
- подключение workspace-папок (`~/dev`, `~/work`, `~/pet-projects`);
- автообнаружение git-репозиториев;
- регистрация/удаление проектов;
- присвоение тегов, политик индексации и синка;
- группировка по workspace;
- поддержка include/exclude rules.

## Сигналы обнаружения проекта
- `.git/`
- `pyproject.toml`
- `package.json`
- `go.mod`
- `Cargo.toml`
- `pom.xml`
- `Dockerfile`
- `docker-compose.yml`
- `.vscode/`

## Режимы подключения
- manual approve;
- auto-add all git repos;
- auto-add with profile;
- auto-add only if config markers present.

---

# 8.3 File Watcher

## Назначение
Отслеживать файловые события и аккуратно агрегировать их в meaningful scan jobs.

## Поддерживаемые события
- create
- update
- delete
- move
- rename
- mass change
- git branch switch (выявляется через git intelligence)

## Обязательные механизмы
- debounce;
- batching;
- ignore patterns;
- backpressure;
- detection of mass changes;
- fallback scheduled scan.

## Рекомендуемые пороги
- одиночные изменения: debounce 15–20 сек;
- серия изменений: debounce 60–90 сек;
- >100 файлов за короткий интервал: partial rebuild;
- branch switch / rebase / checkout: structural scan.

---

# 8.4 Scan Orchestrator

## Назначение
Управлять режимами сканирования и пайплайнами обогащения.

## Режимы
1. **Initial deep scan** — первый полный индекс проекта.
2. **Incremental scan** — changed files only.
3. **Structural rebuild** — смена ветки, массовый refactor, изменение зависимостей.
4. **Scheduled maintenance scan** — ночная/периодическая консолидация.

## Пайплайн
```text
collect file events
→ normalize file list
→ hash compare
→ classify files
→ parse
→ extract symbols
→ update relations
→ summarize
→ embed
→ persist
→ publish artifacts
→ emit metrics
```

---

# 8.5 Parsing & Code Intelligence

## Задача
Не читать код как сырой текст, а извлекать инженерные сущности.

## Источники структурного анализа
- tree-sitter — основной мульти-языковой разборщик;
- Python AST — специализированный экстрактор;
- TypeScript/JS AST;
- YAML/JSON/TOML parsers;
- SQL parser;
- Dockerfile parser;
- Markdown parser.

## Извлекаемые сущности
### File-level
- путь;
- язык;
- хеш;
- размер;
- роль файла;
- imports/exports;
- env usage;
- framework hints;
- entrypoint hints;
- TODO/FIXME/HACK markers.

### Symbol-level
- функция/метод;
- класс;
- интерфейс;
- роут;
- handler;
- cron/job;
- repository/query layer;
- event consumer/producer.

### Module-level
- назначение модуля;
- inbound/outbound dependencies;
- публичные контракты;
- внешние интеграции;
- конфигурация;
- возможные точки риска.

### Project-level
- архитектурное summary;
- точки входа;
- основные потоки данных;
- инфраструктурные зависимости;
- зоны техдолга;
- recent changes digest.

## Поддержка языков v1
- Python
- TypeScript / JavaScript
- JSON / YAML / TOML
- SQL
- Markdown
- Dockerfile
- Shell

## v2 roadmap
- Go
- Rust
- Java
- Kotlin
- Swift
- C#

---

# 8.6 Summarization layer

## Задача
Генерировать summaries, пригодные для retrieval и объяснения контекста.

## Типы summary
### File summary
- что делает файл;
- ключевые сущности;
- внешние зависимости;
- где используется;
- риски/неясности.

### Symbol summary
- назначение символа;
- входы/выходы;
- побочные эффекты;
- связанные сущности.

### Module summary
- роль модуля;
- границы ответственности;
- зависимости;
- важные контракты.

### Architecture summary
- как устроен проект;
- точки входа;
- внешние системы;
- конфиги;
- data flow.

### Change summary
- смысловое изменение файла/модуля;
- что может быть затронуто;
- где смотреть дальше.

## Политика моделей
- дешёвая модель: file/symbol/diff summaries;
- сильная модель: architecture synthesis, сложные module summaries, compression of context packs.

---

# 8.7 Embeddings & Vector Retrieval

## Назначение
Обеспечить semantic retrieval по summaries, symbol descriptions, docs и точечным code chunks.

## Что индексировать векторами
- file summaries;
- symbol summaries;
- module summaries;
- architecture notes;
- selected code chunks;
- README/docs;
- change summaries;
- cross-project patterns.

## Чего не делать
- не индексировать одинаково каждый байт исходников;
- не эмбедить без фильтров generated code;
- не делать re-embed всего проекта при изменении одного файла.

## Хранилище
**Qdrant**.

## Рекомендации
- использовать payload metadata для project/workspace/language/symbol_type/importance/revision;
- заводить payload indexes на часто фильтруемые поля;
- хранить версию embedding model и pipeline version.

---

# 8.8 Graph & Relations layer

## Назначение
Построить explainable graph связей между сущностями.

## Relation types
- imports
- exports
- defines
- calls
- references
- configures
- uses_env
- reads_db
- writes_db
- handles_route
- triggers_job
- publishes_event
- consumes_event
- related_to
- similar_to

## Техническая реализация
На первом production-ready этапе использовать:
- relations в Postgres;
- graph projection в JSON;
- network traversal в коде backend/worker;
- optional caching через NetworkX.

**Не** делать Neo4j обязательным.

---

# 8.9 Git Intelligence

## Назначение
Добавить контекст изменений и поведения репозитория.

## Что анализировать
- текущая ветка;
- recent commits;
- co-change patterns;
- hotspots;
- stale files;
- ownership hints по истории коммитов;
- diff summaries;
- risky files after rebases.

## Зачем это нужно
- приоритизация retrieval;
- impact analysis;
- recent change digest;
- лучшая отладка вопросов «что сломалось после вчерашнего изменения?».

---

# 8.10 Context Pack Builder

## Назначение
Собирать компактный markdown-контекст для Claude/агентов.

## Формат context pack
- project summary;
- relevant modules;
- relevant symbols;
- graph notes;
- recent changes;
- selected raw snippets;
- ambiguities / confidence notes;
- suggested next files.

## Режимы
- `compact`
- `balanced`
- `deep`
- `architecture`
- `debug`
- `diff-aware`

## Цель
Передавать агенту 2–20 KB осмысленного контекста вместо сотен KB сырого кода.

---

# 8.11 Knowledge Publishing / Obsidian Sync

## Назначение
Публиковать человекочитаемую knowledge base в Obsidian.

## Структура vault
```text
Projects/
  <ProjectName>/
    Home.md
    Architecture.md
    Modules/
    Symbols/
    Flows/
    Integrations/
    Recent Changes.md
    Tech Debt.md
    Open Questions.md
    Graph Index.md
```

## Правила публикации
- notes должны быть читабельными, а не dump-артефактами;
- использовать wikilinks;
- включать source paths;
- включать дату обновления;
- включать confidence / freshness indicator.

## Режимы синка
- manual;
- on scan;
- debounced incremental;
- nightly consolidate.

---

# 8.12 Delivery layer

## Интерфейсы
1. **CLI** — основной интерфейс power-user.
2. **Local API** — интеграции, VS Code, automations.
3. **Project `.context/` files** — быстрый вход для Claude.
4. **Obsidian export** — человеческая навигация.
5. **Future VS Code extension** — тонкая интеграция.

---

# 9. Предлагаемый стек

# 9.1 Desktop Agent
- Python 3.12
- watchdog / FSEvents adapter
- Typer
- SQLite
- GitPython
- tree-sitter
- httpx
- pydantic / pydantic-settings
- loguru или structlog

# 9.2 Backend
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Postgres
- Redis или Dragonfly
- Dramatiq или RQ
- uvicorn / gunicorn
- pydantic

# 9.3 Vector Layer
- Qdrant

# 9.4 Optional local AI layer
- Ollama / vLLM / локальный embedding endpoint
- локальный reranker
- локальная summarization model

# 9.5 Front/UI
- минимальный web UI на FastAPI + Jinja/HTMX
- позже, при необходимости, React frontend

# 9.6 Observability
- Prometheus metrics
- OpenTelemetry optional
- structured JSON logs
- health endpoints

---

# 10. Почему именно такой стек

## FastAPI
Быстро, типизированно, предсказуемо, удобно для local API и backend.

## Postgres
Даст нормальную модель данных, relations, migrations, аналитику и future-proof для production.

## Qdrant
Подходит для self-hosted vector retrieval, фильтрации по payload и snapshot-based recovery.

## Redis/Dragonfly + Dramatiq/RQ
Упрощённые, но production-пригодные очереди и фоновые задачи без перегруза стеком.

## SQLite локально
Отлично подходит как агентский cache/state store.

## tree-sitter
Критически важен для symbol-aware индексации.

---

# 11. Разделение на репозитории и модули

Рекомендуемая структура монорепозитория решения:

```text
dev-context/
  apps/
    agent/
    backend/
    worker/
    cli/
    web/
  libs/
    core/
    config/
    parsers/
    graph/
    retrieval/
    embeddings/
    summarization/
    obsidian/
    gitintel/
    telemetry/
    policies/
  deploy/
    docker-compose/
    launchd/
  docs/
    architecture/
    adr/
```

---

# 12. Data model

## 12.1 Core entities
- Workspace
- Project
- Scan
- ScanJob
- File
- Symbol
- Module
- Relation
- Summary
- EmbeddingRecord
- ChangeEvent
- ContextPack
- SyncArtifact
- RetrievalTrace
- UserPreference
- ProjectPolicy

## 12.2 Пример полей

### Project
- id
- workspace_id
- name
- slug
- local_path
- repo_url
- default_branch
- current_branch
- languages
- tags
- scan_policy
- obsidian_enabled
- privacy_mode
- status
- created_at
- updated_at

### File
- id
- project_id
- path
- normalized_path
- language
- role
- size_bytes
- content_hash
- parser_version
- last_scan_id
- importance_class
- is_generated
- is_binary
- is_deleted
- updated_at

### Symbol
- id
- project_id
- file_id
- name
- fq_name
- symbol_type
- signature
- parent_symbol_id
- visibility
- start_line
- end_line
- summary_id
- updated_at

### Relation
- id
- project_id
- src_entity_type
- src_entity_id
- relation_type
- dst_entity_type
- dst_entity_id
- weight
- confidence
- provenance

### Summary
- id
- project_id
- entity_type
- entity_id
- summary_type
- model_name
- model_version
- text
- text_hash
- freshness_score
- confidence_score
- created_at

### ContextPack
- id
- project_id
- query
- mode
- assembled_text
- size_bytes
- retrieval_trace_id
- created_at

---

# 13. Конфигурационная модель

## Уровни конфигурации
1. global config
2. workspace config
3. project config

## Правило наследования
`global defaults -> workspace overrides -> project overrides`

## Пример `~/.devcontext/config.yaml`
```yaml
backend:
  url: http://127.0.0.1:8080
  api_key_env: DEV_CONTEXT_API_KEY

watcher:
  debounce_single_seconds: 20
  debounce_batch_seconds: 75
  max_mass_change_threshold: 100

obsidian:
  vault_path: /Users/you/Documents/Obsidian/MainVault
  root_folder: Projects
  sync_mode: debounced

rag:
  qdrant_collection_prefix: devctx
  retrieval_default_mode: balanced

workspaces:
  - path: /Users/you/dev
    auto_discover: true
    include_git_repos_only: true
    defaults:
      scan_policy: balanced
      obsidian_enabled: true
      auto_watch: true
      ignore:
        - .git
        - node_modules
        - dist
        - build
        - .next
        - .venv
        - __pycache__
```

---

# 14. Политики индексации

## 14.1 Scan policy
- `light`
- `balanced`
- `deep`

### Light
- changed files only;
- быстрые summaries;
- минимум graph refresh.

### Balanced
- changed files + связанное окружение;
- update relations;
- wiki refresh.

### Deep
- полная переоценка структуры;
- architecture resynthesis;
- recompute selected embeddings;
- thorough graph refresh.

## 14.2 Privacy policy
- `local_only`
- `metadata_only`
- `summaries_only`
- `summaries_and_embeddings`
- `raw_snippets_allowed`

## 14.3 Importance policy
- `high`
- `medium`
- `low`

Нужна для выбора частоты reindex и глубины summarization.

---

# 15. Retrieval architecture

# 15.1 Multi-stage retrieval

```text
query
→ resolve scope (project / global)
→ retrieve project/module summaries
→ retrieve symbol candidates
→ graph expansion
→ vector retrieval
→ rerank
→ fetch raw snippets
→ assemble context pack
```

# 15.2 Ranking factors
- semantic relevance;
- exact symbol/path match;
- graph distance;
- recency bonus;
- entrypoint proximity;
- importance class;
- file confidence;
- git hotspot bonus;
- project-local priority.

# 15.3 Scopes
- current project;
- selected project list;
- workspace-wide;
- global across all projects.

# 15.4 Query modes
- architecture explain;
- bug hunt;
- code navigation;
- diff-aware review;
- cross-project reuse;
- onboarding.

---

# 16. Работа с переписыванием кода: узкие места и меры защиты

Этот раздел критичен. Если систему использовать не только для навигации, но и для **переписывания/редактирования кода**, появляются реальные риски.

## 16.1 Главные узкие места

### 1. Редактирование без полного понимания контрактов
Агент может изменить локальную функцию, не увидев, что она влияет на API, тесты, фоновые задачи и соседние модули.

**Меры:**
- перед edit-задачами всегда строить impact set: callers, imports, tests, config usage, routes;
- перед выдачей patch заставлять retrieval собирать `edit pack`, а не обычный context pack;
- требовать explicit preflight check.

### 2. Refactor across files without migration plan
Массовый rename или перенос логики без плана ломает проект.

**Меры:**
- отдельный режим `refactor`;
- сначала plan artifact;
- потом patch generation;
- потом test/lint/typecheck;
- потом diff summary.

### 3. Editing generated/vendor/build artifacts
Агент может начать менять то, что вообще не должно трогаться.

**Меры:**
- denylist по путям;
- project policy `write_protected_paths`;
- hook-проверка перед применением diffs.

### 4. Large context drift
Агент получил устаревший context pack, пока код уже поменялся локально.

**Меры:**
- version stamp на context pack;
- предупреждение при diff between pack revision and current hash;
- invalidation on file change.

### 5. Hidden config coupling
Изменение логики ломает env/config/docker/infra слой.

**Меры:**
- отдельные extractors для env keys, compose, Dockerfile, secrets placeholders;
- graph relations `uses_env`, `configures`, `depends_on_service`.

### 6. Incomplete test impact
Агент меняет код, но не понимает какие тесты/линтеры/типчекеры запускать.

**Меры:**
- project profile с test commands;
- mapping file-to-test heuristics;
- hooks для post-edit validation.

### 7. Over-eager autonomous loops
Слишком автономный агент может каскадно менять проект.

**Меры:**
- режимы autonomy;
- write-budget per task;
- require approval for >N files or critical paths;
- checkpoints.

---

# 17. Паттерн безопасной работы с code editing

## 17.1 Режимы задач
### Navigation
Только объяснение и поиск.

### Explain + plan
Показывает, где менять, но не меняет.

### Scoped edit
Правка в заданной области.

### Refactor
Многофайловое изменение с обязательным планом.

### Migration
Изменение кода + конфигов + тестов + документации.

## 17.2 Обязательный жизненный цикл edit-задачи
```text
intent detect
→ edit scope detect
→ build edit pack
→ impact analysis
→ plan
→ patch
→ lint/typecheck/test
→ summarize changes
→ publish review note
```

## 17.3 Что обязательно класть в edit pack
- target files;
- impacted symbols;
- affected tests;
- related configs;
- routes/jobs/events;
- current conventions from CLAUDE.md / project rules;
- known constraints.

---

# 18. Какие агенты добавить в проекты сразу

Ниже — рекомендуемый **постоянный набор subagents / role-agents**, которые должны работать всегда или быть доступны во всех проектах. Это логические агенты; реализация может идти через Claude Code subagents, hooks, local services и project playbooks.

## 18.1 Context Navigator Agent
**Назначение:** всегда первым определяет, какие summaries, symbols и relations нужны.  
**Почему обязателен:** экономит токены и предотвращает бездумное чтение raw code.  
**Триггер:** любой вопрос выше trivial single-file lookup.

## 18.2 Architecture Agent
**Назначение:** отвечает на вопросы уровня архитектуры, data flow, boundaries, dependencies, anti-patterns.  
**Когда нужен:** onboarding, объяснение, impact analysis, design review.

## 18.3 Code Edit Guard Agent
**Назначение:** проверяет границы изменений, write-protected paths, обязательные проверки, style/policy перед применением patch.  
**Когда нужен:** любые edit/refactor/migration задачи.

## 18.4 Test & Validation Agent
**Назначение:** определяет какие проверки запускать и интерпретирует их результат.  
**Когда нужен:** после patch generation и перед завершением задачи.

## 18.5 Git Change Analyst Agent
**Назначение:** summarization последних коммитов, impact from recent changes, hotspot awareness.  
**Когда нужен:** bug hunt, post-merge review, regression analysis.

## 18.6 Documentation / Obsidian Publisher Agent
**Назначение:** обновляет notes, `.context/` файлы, architecture summaries и wiki pages.  
**Когда нужен:** после крупных изменений и по расписанию.

## 18.7 Project Bootstrap Agent
**Назначение:** fast start for new repo — определяет стек, собирает команды, генерирует initial CLAUDE.md / .context / project profile.  
**Когда нужен:** при подключении нового проекта.

## 18.8 Dependency & Security Surface Agent
**Назначение:** следит за зависимостями, секретами, env usage, risky external integrations.  
**Когда нужен:** перед публикацией, при bootstrap, при infra changes.

## 18.9 Optional specialized agents
- DB / migrations agent
- API contract agent
- Frontend flow agent
- Infra / Docker agent
- Workflow/n8n-like agent
- Observability agent

---

# 19. Какие агенты должны быть always-on, а какие on-demand

## Always-on
- Context Navigator
- Code Edit Guard
- Test & Validation
- Git Change Analyst
- Project Bootstrap (при onboarding)

## Usually enabled
- Architecture Agent
- Documentation Publisher
- Dependency & Security Surface

## On-demand
- Migration Agent
- API Contract Agent
- Frontend UX Flow Agent
- Observability Agent

---

# 20. Claude / IDE extension layer: что использовать в проектах всегда

Согласно текущей официальной документации Claude Code, для устойчивой кастомизации важно опираться на несколько механизмов: **CLAUDE.md**, **hooks**, **subagents**, IDE integration и extension layer вокруг Claude Code. Claude Code также официально работает в VS Code и поддерживает IDE workflows, а память между сессиями проектно закрепляется через `CLAUDE.md` и auto memory. citeturn846743search0turn846743search3turn846743search6turn846743search12turn846743search15

## 20.1 Что должно быть в каждом проекте из коробки

### 1. `CLAUDE.md`
Главный persistent instruction file.

### 2. `.context/`
Автогенерируемая папка с:
- `project.md`
- `architecture.md`
- `recent_changes.md`
- `symbol_index.md`
- `edit_policy.md`
- `commands.md`
- `testing.md`

### 3. Hook configuration
Для deterministic действий:
- pre-read guidance;
- pre-edit guard;
- post-edit test run;
- doc update;
- telemetry emit.

### 4. Subagent profiles
Логические роли, перечисленные выше.

### 5. Project profile
Файл с командами:
- install
- lint
- typecheck
- test
- run
- dev
- build

---

# 21. Recommended `CLAUDE.md` baseline

```md
# Project Working Rules

## Context rules
1. Always query `.context/` and knowledge summaries first.
2. Read raw files only when the summaries are insufficient.
3. For edits, build an edit plan before changing multiple files.
4. Prefer symbol-aware navigation over blind file scanning.

## Safety rules
1. Never modify generated, vendor, build, dist, lock or secret files unless explicitly instructed.
2. For changes affecting routes, schemas, jobs, env or migrations, expand impact analysis first.
3. Run the project validation commands after edits.

## Project entrypoints
- Read `.context/project.md`
- Read `.context/architecture.md`
- Read `.context/commands.md`
- Read `.context/testing.md`

## Output style
- Be explicit about impacted files.
- Summarize why each file matters.
- Prefer minimal, reversible patches.
```

---

# 22. Какие hooks сразу добавить

Claude Code официально поддерживает hooks как автоматические shell/HTTP/LLM-triggered действия на этапах жизненного цикла, и именно hooks лучше использовать для детерминированных обязательных операций, а не полагаться на «агент сам догадается». citeturn846743search6turn846743search15

## 22.1 Preflight Context Hook
**Когда:** перед сложным ответом или edit-задачей.  
**Что делает:**
- проверяет свежесть `.context/`;
- при необходимости запрашивает новый context pack;
- добавляет guidance для current task mode.

## 22.2 Pre-Edit Guard Hook
**Когда:** перед любым write/diff.  
**Что делает:**
- проверяет write-protected paths;
- определяет scope size;
- требует plan mode для >N файлов;
- запрещает редактировать generated paths.

## 22.3 Post-Edit Validation Hook
**Когда:** сразу после patch.  
**Что делает:**
- запускает lint/typecheck/tests согласно project profile;
- собирает краткий validation summary.

## 22.4 Change Summary Hook
**Когда:** после успешного редактирования.  
**Что делает:**
- генерирует diff summary;
- обновляет `recent_changes.md`;
- обновляет affected notes in Obsidian.

## 22.5 Secrets & Risk Hook
**Когда:** до commit/export/review.  
**Что делает:**
- проверяет секреты, env usage, accidental exposure.

## 22.6 Context Drift Hook
**Когда:** при long-running sessions.  
**Что делает:**
- сравнивает revision context pack с текущими hashes;
- предупреждает, что контекст устарел.

---

# 23. Какие плагины / расширения учитывать и как избежать пересечений

Тут важно разделять **плагины IDE/Claude** и **плагины Obsidian**.

## 23.1 Claude / IDE / project-level integrations

### Обязательные слои
- Claude Code VS Code integration;
- CLAUDE.md;
- hooks;
- project `.context/` artifacts;
- local `ctx` CLI.

### Риски пересечения
1. **Claude hooks vs внешний watcher**
   - нельзя заставлять оба механизма параллельно и без координации пересобирать контекст;
   - hooks должны только триггерить lightweight refresh/check, а не full scan.

2. **IDE extension vs local API/CLI**
   - extension не должна дублировать retrieval logic;
   - retrieval живёт в backend/local service, extension только вызывает его.

3. **Auto memory vs project memory**
   - не смешивать персональные привычки и проектные правила;
   - проектные правила — только в `CLAUDE.md` / `.context/`.

## 23.2 Obsidian plugins: рекомендуемый набор

Obsidian официально поддерживает каталог community plugins, а 3D Graph доступен как community plugin; для бета-версий и нестандартной установки у 3D Graph используется BRAT. citeturn846743search1turn846743search4

### Рекомендуемый набор для этой системы
1. **Dataview**
   - для построения представлений по project notes;
   - useful для dashboards, recent changes, tech debt.

2. **Tasks**
   - для action items по tech debt / follow-ups.

3. **Templater**
   - для шаблонов project pages / ADR / bootstrap notes.

4. **BRAT**
   - нужен, если используешь beta-only плагины вроде некоторых graph plugins.

5. **3D Graph**
   - только как дополнительная визуализация;
   - не основной navigation layer.

6. **Extended Graph** или аналогичный расширенный graph plugin
   - если нужен более наглядный graph analysis.

7. **QuickAdd**
   - удобно для ручного добавления архитектурных наблюдений.

### Что не стоит делать
- не превращать Obsidian в runtime-engine;
- не вешать на него live automation всего пайплайна;
- не полагаться на graph visualization как на primary retrieval.

## 23.3 Основные пересечения и как их развести

### Obsidian Graph vs internal code graph
- internal graph — source of truth для retrieval;
- Obsidian graph — только human-friendly projection.

### Dataview vs backend search
- Dataview нужен для dashboard и note views;
- retrieval и semantic search должны жить в backend.

### BRAT / beta plugins vs стабильность vault
- beta plugins включать только в отдельном profiling слое;
- базовая работа knowledge base должна идти без зависимости от бета-фич.

---

# 24. Быстрый старт нового проекта

Ниже описан обязательный bootstrap flow.

## 24.1 Auto-detect
Система находит новый репозиторий в workspace.

## 24.2 Classification
Определяет стек, package manager, test commands, framework, infra markers.

## 24.3 Bootstrap profile generation
Генерирует:
- `CLAUDE.md`
- `.context/project.md`
- `.context/commands.md`
- `.context/testing.md`
- `.context/edit_policy.md`
- `.context/recent_changes.md`

## 24.4 Initial deep scan
- parse tree;
- symbols;
- summaries;
- graph;
- embeddings;
- architecture overview.

## 24.5 Optional Obsidian sync
Создаётся папка проекта и набор заметок.

## 24.6 Bootstrap report
Пользователю выводится:
- detected stack;
- install/run/test/build commands;
- entrypoints;
- risk areas;
- recommended agents.

---

# 25. Пример bootstrap output

```text
Project detected: support-bot
Language stack: Python, YAML, Dockerfile
Framework hints: FastAPI, Celery
Entrypoints:
- app/main.py
- worker.py
- docker-compose.yml

Generated:
- CLAUDE.md
- .context/project.md
- .context/architecture.md
- .context/commands.md
- .context/testing.md

Suggested always-on agents:
- Context Navigator
- Code Edit Guard
- Test & Validation
- Git Change Analyst
```

---

# 26. Project profiles: что должно быть в каждом проекте

## 26.1 Required project metadata file
Например `.devcontext/project.yaml`

```yaml
project_name: support-bot
scan_policy: balanced
privacy_mode: summaries_and_embeddings
importance_defaults:
  core_paths:
    - app/
    - src/
    - services/
  ignored_paths:
    - node_modules/
    - dist/
    - build/
    - .venv/
commands:
  install: poetry install
  dev: poetry run uvicorn app.main:app --reload
  lint: poetry run ruff check .
  typecheck: poetry run mypy .
  test: poetry run pytest -q
protected_paths:
  - alembic/versions/
  - generated/
  - vendor/
```

## 26.2 Почему это важно
Без project profile агент не знает:
- какие команды запускать;
- что считается generated code;
- что можно/нельзя менять;
- где core logic, а где шум.

---

# 27. Стратегия хранения и multitenancy внутри твоей личной платформы

Qdrant рекомендует не плодить лишние коллекции на каждый маленький изолят, а использовать payload-based разделение там, где это подходит; при этом коллекции должны проектироваться под тип данных и retrieval strategy. Для производительности фильтрации payload-поля нужно индексировать. citeturn846743search5turn846743search11turn846743search14turn846743search17turn846743search20

## Рекомендация
Использовать **ограниченное число коллекций**, например:
- `devctx_summaries`
- `devctx_symbols`
- `devctx_chunks`
- `devctx_patterns`

А разделение по проектам держать в payload:
- `project_id`
- `workspace_id`
- `language`
- `entity_type`
- `importance`
- `revision`
- `privacy_mode`

Это проще в эксплуатации, чем «по коллекции на каждый проект».

---

# 28. Backup, recovery и durability

Qdrant поддерживает snapshots на уровне коллекций; это нужно учитывать как обязательную часть recovery story. citeturn846743search2turn846743search8

## Что бэкапить
- Postgres;
- Qdrant snapshots;
- generated artifacts (`.context`, wiki export);
- config files;
- agent state cache optional.

## Recovery strategy
1. Поднять Postgres.
2. Восстановить Qdrant snapshot.
3. Поднять backend и worker.
4. Поднять desktop agent.
5. Запустить selective verification scan.

## Важный принцип
Даже если vector layer недоступен, система должна:
- продолжать работать в summary-first / graph-first degraded mode;
- уметь потом догнать embeddings асинхронно.

---

# 29. Наблюдаемость и эксплуатация

## 29.1 Метрики
- scan_duration_seconds
- changed_files_count
- indexing_lag_seconds
- retrieval_latency_ms
- context_pack_size_bytes
- estimated_token_savings
- embedding_queue_depth
- parser_failures_total
- obsidian_sync_duration_seconds
- stale_projects_count

## 29.2 Health endpoints
- `/health/live`
- `/health/ready`
- `/health/dependencies`
- `/health/agent-sync`

## 29.3 Логи
Каждое событие должно логироваться с полями:
- project_id
- scan_id
- job_id
- stage
- duration_ms
- file_count
- error_type
- retry_count

## 29.4 Retry policy
Нужна для:
- network errors;
- model timeouts;
- qdrant/postgres unavailable;
- parse crashes;
- vault locked;
- branch changed mid-scan.

---

# 30. Security model

## Принципы
- local-first по умолчанию;
- remote sync только по политике;
- secrets не хранятся в plaintext config;
- API auth обязателен даже для local API, если он доступен не только loopback;
- журналы не должны утекать с raw snippets сверх policy.

## Что хранить отдельно
- API keys;
- embedding service creds;
- remote backend auth;
- optional Git provider tokens.

## Режимы безопасности
- local only;
- summaries only;
- embeddings only;
- no raw code off-machine.

---

# 31. Deployment model

## На Mac
- `dev-context-agent`
- `ctx` CLI
- local SQLite cache
- launchd plist

## На сервере
Через Docker Compose:
- backend
- worker
- postgres
- redis/dragonfly
- qdrant
- optional local-llm/embedding service
- optional admin ui

## Почему не Kubernetes
Для личной/малой инженерной платформы это избыточно и сильно усложняет поддержку.

---

# 32. Пример Docker Compose набора

```text
services:
  backend
  worker
  postgres
  dragonfly
  qdrant
  optional-embeddings
  optional-reranker
```

---

# 33. CLI: обязательные команды

```bash
ctx init
ctx workspace add ~/dev
ctx project list
ctx project add ~/dev/support-bot
ctx project inspect support-bot
ctx scan support-bot --deep
ctx watch start
ctx ask support-bot "where is token refresh logic"
ctx pack support-bot "explain billing flow" --mode architecture
ctx changes support-bot --since 7d
ctx graph support-bot
ctx obsidian sync support-bot
ctx doctor
ctx backup create
```

---

# 34. API: обязательные endpoints

## Projects
- `POST /projects/register`
- `GET /projects`
- `GET /projects/{id}`
- `POST /projects/{id}/scan`
- `POST /projects/{id}/resync`

## Retrieval
- `POST /context/pack`
- `POST /context/query`
- `GET /projects/{id}/graph`
- `GET /projects/{id}/changes`

## Health
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`

## Artifacts
- `GET /projects/{id}/artifacts`
- `POST /projects/{id}/obsidian-sync`

---

# 35. Обязательные артефакты в проекте

В каждом подключённом проекте должны автоматически поддерживаться:

```text
.context/
  project.md
  architecture.md
  commands.md
  testing.md
  edit_policy.md
  recent_changes.md
  symbol_index.md
  bootstrap_report.md
```

## Назначение
Это самый быстрый вход для Claude, IDE и человека.

---

# 36. Политика исключений

Обязательно исключать из индекса:
- `.git/`
- `node_modules/`
- `dist/`
- `build/`
- `.next/`
- `.cache/`
- `.venv/`
- `__pycache__/`
- `coverage/`
- бинарники
- lockfiles (опционально summary-only)
- generated code
- vendor dirs
- архивы
- большие лог-файлы

---

# 37. Performance budget

## Цели
- incremental scan после small edit: до 2–10 секунд на постановку и обработку;
- context pack retrieval: до 1–3 секунд в обычном режиме;
- initial scan small/medium repo: до нескольких минут;
- nightly maintenance: асинхронно, без блокировки IDE workflow.

## Ключевые оптимизации
- content hash, а не timestamp;
- дебаунс;
- importance-aware indexing;
- partial graph recompute;
- selective embeddings;
- background architecture synthesis.

---

# 38. Метрика пользы: как считать экономию токенов

Нужно сохранять:
- estimated raw bytes avoided;
- average summary-first hit rate;
- raw snippet necessity rate;
- average context pack size;
- avg files avoided per task;
- projected token savings.

Это поможет доказать, что платформа реально работает, а не просто красивая.

---

# 39. Основные риски проекта

## Технические
- сложность многоязычного разбора;
- ложные graph relations;
- устаревание summaries;
- рост объёма индекса;
- latency на тяжёлых проектах.

## Продуктовые
- слишком сложный initial setup;
- лишний шум в Obsidian;
- попытка использовать систему как полностью автономного кодера вместо умного контекстного слоя.

## Эксплуатационные
- недоступность vector DB;
- branch drift;
- build artifacts leaking into index;
- beta-плагины Obsidian ломают стабильность vault.

---

# 40. Decisions / ADR summary

## ADR-001
**Использовать modular monolith + worker, а не микросервисы.**

## ADR-002
**Использовать desktop agent на macOS как обязательный компонент.**

## ADR-003
**Сделать graph-first, summary-first retrieval.**

## ADR-004
**Использовать Postgres + Qdrant + SQLite cache.**

## ADR-005
**Obsidian является human-facing projection, но не source of truth.**

## ADR-006
**Для edit-задач обязателен edit pack + guardrail pipeline.**

## ADR-007
**Проектные инструкции живут в `CLAUDE.md` и `.context/`, а не в хаотичной памяти агента.**

---

# 41. Что считаю обязательным MVP уровня production-ready v1

- auto project discovery;
- project registry;
- watcher with debounce;
- incremental scan;
- symbol extraction;
- file/module/project summaries;
- graph relations;
- embeddings in Qdrant;
- retrieval API;
- context pack builder;
- git-aware scoring;
- CLAUDE.md bootstrap;
- hooks baseline;
- `.context/` artifacts;
- Obsidian sync;
- backups / snapshots;
- logs / metrics / health;
- edit guardrails.

---

# 42. Что не включать в первую реализацию

- полноценный collaborative multi-user режим;
- жёсткая привязка к одной IDE;
- heavy frontend first;
- Neo4j как обязательный dependency;
- автономный массовый rewrite кода без approval checkpoints.

---

# 43. Практическая рекомендация по внедрению

## Фаза 1 — Foundation
- backend + worker + postgres + qdrant + queue;
- desktop agent + project discovery + watcher;
- file/symbol parsing;
- `.context/` bootstrap;
- basic CLI.

## Фаза 2 — Intelligence
- summaries;
- graph relations;
- git intelligence;
- context packs;
- Obsidian sync;
- edit guard pipeline.

## Фаза 3 — Power user
- VS Code light integration;
- richer hooks;
- cross-project pattern retrieval;
- dashboards in Obsidian / web UI;
- optional local models.

---

# 44. Финальная формулировка решения

Нужно строить не «поисковик по репозиториям» и не «ещё один RAG», а:

> **Developer Context Platform** — локально-удалённую платформу инженерной памяти, которая автоматически превращает проекты на macOS в управляемый слой контекста для Claude, IDE и человека, минимизирует повторное чтение кода, повышает точность навигации и делает редактирование безопаснее.

---

# 45. Приложение: короткий checklist готовности решения

## Архитектура
- [ ] Desktop agent
- [ ] Backend API
- [ ] Worker
- [ ] Postgres
- [ ] Qdrant
- [ ] Queue layer

## Проекты
- [ ] Auto discovery
- [ ] Project profiles
- [ ] `.context/` artifacts
- [ ] `CLAUDE.md`
- [ ] Ignore policies

## Retrieval
- [ ] Summaries
- [ ] Symbols
- [ ] Graph relations
- [ ] Git intelligence
- [ ] Context packs

## Safety
- [ ] Pre-edit guard
- [ ] Post-edit validation
- [ ] Protected paths
- [ ] Context drift detection

## Knowledge base
- [ ] Obsidian export
- [ ] Recent changes
- [ ] Architecture notes
- [ ] Tech debt notes

## Operability
- [ ] Metrics
- [ ] Health checks
- [ ] Retries
- [ ] Backups
- [ ] Snapshots

---

# 46. Приложение: reference points, которые нужно учитывать при реализации

При реализации стоит ориентироваться на текущие официальные возможности Claude Code в VS Code, механизм `CLAUDE.md`, hooks и extension layer, а также на возможности Obsidian community plugins и операционные рекомендации Qdrant по коллекциям, payload filters и snapshots. citeturn846743search0turn846743search1turn846743search2turn846743search3turn846743search4turn846743search5turn846743search6turn846743search8turn846743search11turn846743search14turn846743search15turn846743search17turn846743search20
