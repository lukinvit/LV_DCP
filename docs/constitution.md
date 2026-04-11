# LV_DCP Constitution

Это не гайдлайн и не wishlist. Это **неизменяемые правила проекта**. Любое решение, нарушающее конституцию, должно либо быть отвергнуто, либо потребовать явного ADR, изменяющего конституцию (и тогда конституция обновляется, а не обходится).

**Аудитория:** автор проекта, все будущие Claude-сессии, все агенты и субагенты. Перед любым планом или изменением — прочитать этот файл.

---

## I. Миссия

LV_DCP — **инженерная память**, а не поисковик по коду. Её единственная цель:

> Уменьшить стоимость и повысить качество работы разработчика и LLM-агентов с большой кодовой базой через управляемый, инкрементный, измеряемый слой контекста.

Если фича не снижает стоимость токенов, не повышает точность retrieval или не повышает безопасность правок — она не принадлежит LV_DCP.

---

## II. Фундаментальные инварианты (никогда не нарушать)

### 1. Graph-first, summary-first, raw-last
Retrieval всегда идёт в порядке: project summary → module summary → symbol candidates → graph expansion → vector retrieval → rerank → targeted raw snippets. Чтение сырого кода — **последний** шаг, не первый. Нарушение = баг.

### 2. Incremental by default
Пересчитываем только изменившееся и связанное. Content hash, не timestamp. Полный re-scan — исключение, требующее явной команды или branch switch / rebase / mass-change триггера. Нарушение = регрессия.

### 3. Deterministic around LLM
Watcher, hashing, parsing, graph relations, policies, cache keys — детерминированы и воспроизводимы. LLM используется **только** для synthesis (summaries, architecture notes). Любой детерминированный шаг, зависящий от LLM, = баг.

### 4. Measurement before optimization
Никакое изменение retrieval, парсеров или графа не мержится без обновлённых метрик eval harness (см. [ADR-002](adr/002-eval-harness.md)). «Кажется лучше» не существует. Метрика или не было улучшения.

### 5. Budgets are contracts
Бюджеты из [ADR-001](adr/001-budgets.md) — жёсткие ограничения, не аспирации. Превышение бюджета = **блокирует релиз**, а не открывает обсуждение.

### 6. Single-writer data model
Desktop agent = source of truth для file state. Backend = source of truth для retrieval state. Two-way sync запрещён (см. [ADR-003](adr/003-single-writer-model.md)). Нарушение = архитектурный долг первой категории.

### 7. Qdrant payload isolation, not collection-per-project
Фиксированный набор коллекций (`devctx_summaries`, `devctx_symbols`, `devctx_chunks`, `devctx_patterns`). Изоляция через payload-поля + payload indexes. Collection-per-project запрещено.

### 8. Async all the way
В Python коде: никакого sync I/O в async-контексте. Никакого `requests`, никакого sync SQLAlchemy session, никаких блокирующих `time.sleep` или `open().read()` больших файлов. Нарушение = CRITICAL в code review.

### 9. Modular monolith boundaries
- `apps/*` могут импортировать из `libs/*`. **Никогда** из соседних `apps/*`.
- `libs/*` **никогда** не импортируют из `apps/*`.
- `libs/core` зависит только от stdlib + pydantic.
- Бизнес-логика в `services/` внутри `apps/*`, **никогда** в route handlers.

### 10. Edit safety is first-class
Перед любым multi-file изменением — edit pack + impact analysis + plan. Context pack ≠ edit pack. `write_protected_paths` соблюдается абсолютно (generated, vendor, dist, lockfiles, applied Alembic revisions). Нарушение = аварийный rollback.

### 11. Eat your own dog food
Как только CLI умеет `ctx scan`, LV_DCP обязан индексировать **сам себя**, и разработка продолжается с использованием собственного инструмента. Если инструмент недостаточно хорош для своего автора, он недостаточно хорош вообще.

### 12. No secrets in repo, no exceptions
Секреты только в `.env` (gitignored) и `.env.example` (документирующий шаблон без значений). Ни в `CLAUDE.md`, ни в compose.yml, ни в плистах, ни в ADR. Обнаружение секрета в репо = немедленная ротация + git history cleanup.

---

## III. Scope discipline

### Что LV_DCP — **НЕ**

- Не мультитенантная SaaS-платформа.
- Не автоматический code generator без human review.
- Не replacement для IDE, type checker, linter.
- Не полная замена grep/ripgrep — это дополнение поверх них.
- Не Kubernetes-система. Docker Compose + launchd — это потолок сложности.
- Не Neo4j-based. Relations живут в Postgres, graph traversal — в коде.

### YAGNI правила

- **Два privacy режима**, не пять: `local_only`, `full_sync`. Добавление третьего требует ADR.
- **Два context pack режима** в фазах 0–3: `navigate`, `edit`. Остальные (`architecture`, `debug`, `diff-aware`) — фаза 4+.
- **Один язык** в фазе 1 (Python) + deterministic парсеры для Markdown/YAML/JSON/TOML. TypeScript, Go, Rust — по одному с полным eval на каждом.
- **pgvector/sqlite-vss в фазах 1–2**. Qdrant вводится только если метрики упираются в потолок предыдущего решения.
- **Worker сворачивается в backend** для MVP (APScheduler / arq). Отдельный worker process — фаза 3+.
- **Obsidian sync — фаза 3+**. В ранних фазах пишем `.context/*.md` в репо, пользователь symlink'ает сам.
- **Cross-project patterns — фаза 3+**. Single-project сначала.

---

## IV. Non-negotiable deliverables

Ни одна фаза не считается завершённой без этих артефактов:

1. **Обновлённый eval harness** с пройденными порогами для данной фазы.
2. **Зелёный `make lint typecheck test`**.
3. **Dogfood report** в `docs/dogfood/phase-N.md`, который одновременно выступает как Phase CHANGELOG: обязан содержать cost/latency на канареечном репо (LV_DCP сам), eval метрики, changed surface, known issues.
4. **Обновлённая конституция или ADR**, если по ходу фазы были приняты решения, влияющие на правила.

---

## V. Процесс принятия решений

### ADR required когда:
- Изменение любого инварианта из Раздела II
- Добавление новой технологии в stack
- Изменение границ между `apps/` и `libs/`
- Изменение модели данных (таблицы, Qdrant payload schema, API контракты)
- Превышение любого бюджета из ADR-001
- Введение нового privacy или context pack режима

### ADR NOT required для:
- Рефакторинга внутри одного модуля
- Добавления тестов
- Обновления зависимостей в пределах semver
- Правок документации

ADR хранятся в [docs/adr/](adr/), номеруются последовательно, никогда не редактируются после принятия — только superseded новыми ADR.

---

## VI. Источник истины в конфликтах

При любом противоречии побеждает **более строгий источник** в этом порядке:

1. Эта конституция
2. ADRs (в порядке номеров — более новый > более старый, если явно superseded)
3. CLAUDE.md (рабочие правила)
4. docs/tz.md (исходное ТЗ — справочник и вдохновение, но **не** текущий контракт)
5. Комментарии в коде

ТЗ — это не контракт. ТЗ — это стартовая точка. Конституция и ADRs — контракт.
