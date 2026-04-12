# LV_DCP — Developer Context Platform

Локально-удалённая инженерная память: превращает локальные проекты на macOS в управляемый слой контекста для Claude, IDE и человека. Снижает расход токенов на повторное чтение кода, строит граф связей и публикует knowledge base в Obsidian.

## Обязательное чтение перед любым изменением

В порядке приоритета (более строгий источник побеждает при конфликте):

1. **[docs/constitution.md](docs/constitution.md)** — неизменяемые правила проекта. Источник истины #1.
2. **[docs/adr/](docs/adr/)** — принятые архитектурные решения:
   - [ADR-001 Budgets](docs/adr/001-budgets.md) — жёсткие cost/latency/resource бюджеты
   - [ADR-002 Eval harness](docs/adr/002-eval-harness.md) — retrieval quality как контракт
   - [ADR-003 Single-writer model](docs/adr/003-single-writer-model.md) — agent vs backend ownership
3. **Этот файл (CLAUDE.md)** — рабочие конвенции.
4. **[docs/tz.md](docs/tz.md)** — исходное ТЗ (1842 строки). Стартовая точка, **не** текущий контракт.
5. **[docs/superpowers/plans/](docs/superpowers/plans/)** — действующий план фазы.

## Стек

- **Язык:** Python 3.12 (strict typing, async-first)
- **Backend:** FastAPI + Uvicorn, pydantic v2, pydantic-settings
- **ORM:** SQLAlchemy 2.x async + Alembic (async env.py)
- **БД:** Postgres 16 (primary), SQLite (локальный кэш desktop-агента)
- **Vector:** Qdrant — **фиксированный набор коллекций**, изоляция по payload (`project_id`), не по коллекциям
- **Queue / cache:** Redis 7 или Dragonfly; Dramatiq или RQ для worker-задач
- **Parsing:** tree-sitter (multi-lang), Python AST для Python-специфики
- **Desktop agent:** Python + watchdog/FSEvents, managed by launchd
- **LLM:** Claude API по умолчанию; опциональный локальный слой (Ollama/vLLM)

## Структура (modular monolith + workers)

```
apps/
  agent/     macOS daemon (watcher, project discovery, local cache, sync)
  backend/   FastAPI — retrieval API, project registry, context packs
  worker/    Dramatiq/RQ — parsing, summarization, embedding pipelines
  cli/       `ctx` CLI
  web/       минимальный admin UI (Jinja/HTMX, позже)
libs/
  core/      домены и shared types (минимум deps)
  config/    pydantic-settings, слои global→workspace→project
  parsers/   tree-sitter + экстракторы символов
  graph/     relations + проекция
  retrieval/ multi-stage pipeline (summary → symbol → graph → vector → rerank)
  embeddings/Qdrant client + embedding adapter
  summarization/
  obsidian/  vault sync
  gitintel/  git-aware enrichment
  telemetry/
  policies/  scan / privacy / importance
deploy/
  docker-compose/
  launchd/
docs/
  tz.md            # полное ТЗ
  architecture/
  adr/
```

### Правила зависимостей
- `apps/*` могут импортировать из `libs/*`, **никогда** из соседних `apps/*`
- `libs/*` **не** импортируют из `apps/*`
- `libs/core` зависит только от stdlib + pydantic
- Бизнес-логика в `services/` внутри соответствующего `apps/*`, **не** в роутах

## Принципы работы (из ТЗ §7, §15)

1. **Graph-first, summary-first, raw-last.** Retrieval порядок: project summary → module summary → symbols → graph expansion → vector → rerank → targeted raw snippets. Никогда не читаем весь код сразу.
2. **Incremental by default.** Пересчитываем только изменившееся и связанное. Content hash, а не timestamp.
3. **Local-first, remote-assisted.** Desktop-агент владеет доступом к ФС. Backend — долговременное хранение, тяжёлые пайплайны, retrieval.
4. **Deterministic around LLM.** LLM — только для synthesis. Watcher, hashing, parsing, relations, policies — детерминированы.
5. **Modular monolith, не микросервисы.** Простота эксплуатации превыше модной архитектуры.

## Безопасность правок (ТЗ §16–§17)

**Обязательный цикл edit-задачи:** intent → edit scope → build edit pack → impact analysis → plan → patch → lint/typecheck/test → change summary.

- Перед любым multi-file refactor — **план артефактом**, потом patch
- `write_protected_paths` (generated, vendor, build, dist, lockfiles, `alembic/versions/` — только через новую ревизию) **не** трогать без явной инструкции
- Для изменений, затрагивающих routes / schemas / jobs / env / migrations — расширять impact analysis
- Post-edit: запустить validation commands (см. ниже)

## Команды

```bash
# install (uv — основной менеджер)
make install           # == uv sync

# dev (появятся по фазам)
uv run python -m apps.cli scan <path>              # phase 1
uv run uvicorn apps.backend.main:app --reload      # phase 3+
uv run python -m apps.agent                        # phase 3+
uv run python -m apps.worker                       # phase 3+

# quality (работает с первого дня)
make lint              # ruff check + format --check
make format            # ruff format + --fix
make typecheck         # mypy strict
make test              # pytest, без eval и llm маркеров
make eval              # retrieval evaluation harness

# infra — ТОЛЬКО через удалённый docker context docker-vm
make docker-up         # DOCKER_CONTEXT=docker-vm docker compose up
make docker-down
make docker-logs

# db (phase 3+)
uv run alembic upgrade head
uv run alembic revision -m "message" --autogenerate
```

## Deployment: remote docker context

Вся серверная инфраструктура (Postgres, Qdrant, Redis, backend, worker) запускается **только** через удалённый Docker context `docker-vm` (например `ssh://user@docker.your-host.example:2222`). Локальный Docker Desktop используется только для одноразовых экспериментов.

См. [docs/deployment/docker-context.md](docs/deployment/docker-context.md) для деталей, правил портов, volumes и phase gating.

Любая команда `docker compose` без явного `DOCKER_CONTEXT=docker-vm` в LV_DCP — ошибка. Всегда через `make docker-*` или через переменную окружения.

## Конвенции кода

- **Async везде** — sync I/O запрещён в async path. Блокирующее → `asyncio.to_thread`
- **Pydantic DTO** для API, **SQLAlchemy модели** только для persistence. Никогда `response_model=<ORM>`
- **Типы обязательны** — `Mapped[...]`, return types, Pydantic everywhere. `mypy --strict` как цель
- **Никаких f-strings в SQL** — ORM или `text()` с bindparams
- **Ruff + mypy чистые** до каждого commit
- **Логи через structlog** с полями `project_id`, `scan_id`, `job_id`, `stage`, `duration_ms`
- **Секреты** — только `.env` + `.env.example` в репо; `.env` в `.gitignore`
- **UUID pk** где того требует ТЗ

## Qdrant discipline (ТЗ §27)

- **НЕ** создавать коллекцию на проект. Только фиксированный набор: `devctx_summaries`, `devctx_symbols`, `devctx_chunks`, `devctx_patterns`
- Изоляция через payload: `project_id`, `workspace_id`, `language`, `entity_type`, `importance`, `revision`, `privacy_mode`, `model_version`
- Payload indexes на hot filter fields
- Snapshots — часть backup story, не опционально

## Что НЕ делать (ТЗ §4, §42)

- Kubernetes, Neo4j как обязательные
- Per-project Qdrant collections
- Автономный массовый rewrite кода без approval checkpoints
- Полный re-embed при изменении одного файла
- Синхронный SQLAlchemy где-либо
- Бизнес-логика в route handlers
- Секреты в compose.yml, плистах, CLAUDE.md

## Агенты (вызывать по задаче)

- **fastapi-architect** — дизайн роутеров, DI, lifespan, middleware
- **db-expert** — Postgres schema, Alembic, Qdrant collections, Redis
- **system-analyst** — impact analysis перед multi-file изменениями
- **test-runner** — pytest-asyncio, фикстуры, TestContainers
- **devops-deployer** — docker compose, launchd plist, .env
- **code-reviewer** — перед коммитом крупных изменений

## Фазы внедрения (ТЗ §43)

1. **Foundation** — backend + worker + postgres + qdrant + queue; desktop agent + watcher + file/symbol parsing; `.context/` bootstrap; базовый CLI
2. **Intelligence** — summaries, graph relations, git intelligence, context packs, Obsidian sync, edit guard pipeline
3. **Power user** — VS Code integration, hooks, cross-project patterns, dashboards, optional local models

Начинаем с фазы 1. MVP цели — см. ТЗ §41.

<!-- LV_DCP managed section — do not edit manually -->
## LV_DCP Context Discipline (ОБЯЗАТЕЛЬНО)

**BLOCKING REQUIREMENT:** This project is indexed by LV_DCP. You MUST call `lvdcp_pack` BEFORE using Grep, Read, or any file exploration tool. This is not optional.

**EVERY task starts with lvdcp_pack:**

- Navigate: `lvdcp_pack(path="/path/to/LV_DCP", query="your question", mode="navigate")`
- Edit: `lvdcp_pack(path="/path/to/LV_DCP", query="task description", mode="edit")`

**Why:** The pack returns 2-20 KB of ranked files and symbols in <1 second. Without it, you grep-walk the entire repo (~1M+ tokens). The pack is 1000x cheaper and already knows the dependency graph.

**After receiving the pack:** Read only the top files from it. Do NOT grep the entire repo.
<!-- end LV_DCP managed section -->
