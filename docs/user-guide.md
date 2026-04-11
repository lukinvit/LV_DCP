# LV_DCP — гид пользователя

Практический гид по тому, что делает `ctx` сейчас, как подключить его к твоему проекту, и какой реальный value он даёт. Ориентирован на Phase 1 — текущую рабочую версию.

---

## 1. Что это за инструмент

**LV_DCP (Developer Context Platform)** — локальный CLI, который превращает любой Python-проект в запрашиваемый индекс файлов, символов и связей между ними.

В двух предложениях:

> Ты задаёшь вопрос на человеческом языке («где логика refresh токена?»), LV_DCP возвращает **2–5 конкретных файлов и символов**, которые к этому относятся — вместо того чтобы ты (или Claude Code) читал весь репозиторий подряд.

**Что он НЕ есть:**
- Не заменяет IDE, grep, ripgrep, type checker или linter — он работает поверх них и с ними
- Не автономный code generator — он готовит **контекст** для LLM/человека, но не пишет код сам
- Не SaaS / облако / multi-user — всё локально, один процесс, никаких сервисов

**Текущая стадия:** Phase 1 — фаза deterministic slice. Без LLM, без backend'а, без vector search. Работает полностью офлайн, без API-ключей, бесплатно.

---

## 2. Установка и подключение

### Требования
- macOS или Linux
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (быстрый package manager от Astral — замена poetry)

### Первая установка

```bash
cd ~/Nextcloud/lukinvit.tech/projects/LV_DCP
uv sync --all-extras
```

После этого команда `ctx` запускается через `uv run ctx` **из директории LV_DCP**. Это самый простой вариант — ничего не меняешь в PATH.

### Глобальная установка (опционально)

Если хочешь вызывать `ctx` из любого места без `uv run`:

```bash
cd ~/Nextcloud/lukinvit.tech/projects/LV_DCP
uv pip install -e .
# теперь команда ctx доступна глобально, пока активно текущее окружение
```

### Подключение к проекту

LV_DCP **не требует никакой интеграции** в твой проект. Это внешний инструмент — ты просто показываешь ему путь к проекту, а он создаёт папку `.context/` внутри него:

```
your-project/
├── src/
├── tests/
├── pyproject.toml
└── .context/              ← создаётся LV_DCP'ом
    ├── cache.db           ← SQLite кэш с файлами, символами, связями
    ├── fts.db             ← full-text search индекс
    ├── project.md         ← human-readable обзор проекта
    └── symbol_index.md    ← список всех символов с локациями
```

**Рекомендация:** добавь `.context/` в `.gitignore` целевого проекта. Это локальный кэш, не артефакт для коммита.

---

## 3. Три команды — что делает каждая

### `ctx scan <path>`

Сканирует проект, парсит файлы, строит индекс, пишет артефакты в `.context/`.

```bash
uv run ctx scan ~/dev/my-fastapi-project
# scanned 234 files, 1847 symbols, 3521 relations
```

**Что происходит внутри:**
1. Рекурсивный обход файлов. Автоматически пропускает: `.git/`, `.venv/`, `venv/`, `node_modules/`, `__pycache__/`, `dist/`, `build/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.next/`, `.cache/`, `coverage/`, `.context/` — и `.pyc`, `.pyo`, `.so`, `.log`, `.DS_Store` по расширению.
2. Для каждого Python-файла — stdlib `ast` вытаскивает классы, функции, методы, константы, импорты, same-file вызовы.
3. Для Markdown — regex по заголовкам даёт навигационные якоря.
4. Для YAML/JSON/TOML — валидация синтаксиса (извлечение ключей будет в Phase 2).
5. SHA-256 content hash для каждого файла (основа будущей инкрементальности).
6. Запись в SQLite (`cache.db`) и FTS5 (`fts.db`).
7. Генерация human-readable `project.md` и `symbol_index.md`.

**Файлы, удалённые между запусками `scan`, автоматически удаляются из кэша** (через foreign key cascade). Не надо чистить вручную.

**Скорость:** на 100–200 файлах — ~0.5с. На 500 файлах — по плану ≤ 20с, реально сильно быстрее. LV_DCP индексирует сам себя (111 файлов) за 0.5с.

### `ctx pack <path> "<query>" [--mode navigate|edit]`

Ключевая команда. Превращает запрос в markdown-пакет с релевантными файлами и символами.

#### Navigate mode (по умолчанию) — для вопросов

```bash
uv run ctx pack ~/dev/my-fastapi-project "authentication middleware"
```

Выдаёт что-то вроде:

```markdown
# Context pack — navigate

**Project:** `my-fastapi-project`
**Query:** authentication middleware
**Pipeline:** `phase-1-v0`

## Top files
1. `app/middleware/auth.py` (score 12.34)
2. `app/main.py` (score 5.67)
3. `tests/middleware/test_auth.py` (score 3.21)

## Top symbols
1. `app.middleware.auth.AuthMiddleware`
2. `app.middleware.auth.verify_token`
3. `app.main.create_app`
```

#### Edit mode — для правок

```bash
uv run ctx pack ~/dev/my-fastapi-project "add rate limiting to login" --mode edit
```

Выдаёт файлы, **разделённые по ролям**:

```markdown
# Context pack — edit

**Project:** `my-fastapi-project`
**Intent:** add rate limiting to login
**Pipeline:** `phase-1-v0`

> This is an **edit pack**: files grouped by role so the executor can
> plan a minimal, reversible patch. Run validation after every change.

## Target files
- `app/handlers/auth.py` (score 10.00)
- `app/middleware/rate_limit.py` (score 7.50)

## Impacted tests
- `tests/test_auth.py`
- `tests/middleware/test_rate_limit.py`

## Impacted configs
- `config/rate_limits.yaml`

## Candidate symbols
- `app.handlers.auth.login`
- `app.middleware.rate_limit.RateLimiter`

## Reminder: edit discipline (constitution §II.10)
1. Build minimal plan before patching multiple files
2. Never touch write_protected_paths
3. Run lint + typecheck + tests after every change
4. Summarize the diff when done
```

**Почему это важно:** edit mode явно говорит LLM-агенту «не забудь проверить тесты и конфиги». Это снимает частую ошибку «поправил handler, сломал тест» — типичный провал context-unaware правок.

#### Ретривал под капотом

```
query → SymbolIndex (exact + token match)
      → FTS5 (AND-first, fallback OR, stopwords filtered)
      → merge scores (per-file best-symbol cap + score decay cutoff)
      → top-N files + top-N symbols
      → markdown assembly
```

Всё deterministic. Один и тот же запрос всегда даёт один и тот же результат. Никаких LLM-вызовов, никаких платных API.

### `ctx inspect <path>`

Быстрая статистика индекса без поиска:

```bash
uv run ctx inspect ~/dev/my-fastapi-project
```

```
project: my-fastapi-project
files: 234
  python: 187
  markdown: 32
  yaml: 8
  json: 5
  toml: 2
symbols: 1847
  function: 892
  class: 423
  method: 312
  constant: 120
  module: 100
relations: 3521
  same_file_calls: 1678
  imports: 1109
  defines: 734
```

Полезно чтобы:
- Понять размер и языковой состав проекта за 1 секунду
- Убедиться, что scan нашёл все файлы (если счётчик подозрительно мал — проверь ignore правила)
- Быстро увидеть дисбалансы (например: 500 same_file_calls, но всего 10 defines — подозрительно)

---

## 4. Зачем это реально нужно — 4 use case'а

### 4.1. Экономия токенов в Claude Code / Cursor / Cline

**До LV_DCP:**
> Ты Claude'у: «разберись, где в этом репо refresh token logic»
> Claude читает 30-50 файлов, тратит 50-80K токенов входного контекста, часто ошибается, ты повторяешь вопрос с уточнениями.

**С LV_DCP:**
```bash
uv run ctx pack ~/dev/the-repo "refresh token logic" > /tmp/pack.md
# Затем вставляешь /tmp/pack.md как первый блок контекста в Claude
```

Claude получает 2-5 правильных файлов сразу, тратит 5-10K токенов, отвечает точно с первого раза. Типичная экономия — **10×** по токенам и **2-3×** по времени до ответа.

Это главный value proposition. Остальные use cases — надстройка над этим.

### 4.2. Onboarding в незнакомый проект

Пришёл на чужой проект, не знаешь ни структуры, ни конвенций:

```bash
cd unknown-project
uv run ctx scan .

# 1. Общая картина
cat .context/project.md

# 2. Что внутри — весь список символов с локациями
less .context/symbol_index.md

# 3. Направленные вопросы
uv run ctx pack . "database migrations"
uv run ctx pack . "http handlers"
uv run ctx pack . "background jobs"
uv run ctx pack . "authentication"
uv run ctx pack . "main entry point"
```

За 5 минут получаешь mental model, которая обычно занимает полдня grep'а и чтения README'шек.

### 4.3. Impact analysis перед рефакторингом

Вместо:
```bash
# Классический grep-подход
grep -rn "User.email" .
# получаешь 80 результатов, половина — false positives
```

Сделай:
```bash
uv run ctx pack . "change User model email field" --mode edit
```

Edit pack сразу покажет:
- **Target files** — где живёт сама модель
- **Impacted tests** — которые надо обновить
- **Impacted configs** — которые могут содержать email-related settings

Это не замена grep'у, а дополнение: LV_DCP хорош для **семантических** вопросов («где логика X»), grep — для **синтаксических** («найди точное слово User.email»). Используй оба.

### 4.4. Поиск уже существующих паттернов

Перед написанием нового кода:
```bash
uv run ctx pack . "pagination"
uv run ctx pack . "retry with exponential backoff"
uv run ctx pack . "csv export"
```

Быстро находит существующие реализации в проекте. Снижает дублирование кода. Особенно полезно в больших монорепо и проектах, где ты не помнишь каждый модуль наизусть.

> **Cross-project поиск** («а где я вообще когда-то делал refresh token?» по **всем** моим 25 репам) — Phase 5+, сейчас только внутри одного проекта.

---

## 5. Практический workflow с Claude Code

Самый частый паттерн использования LV_DCP как helper'а для Claude:

```bash
# 1. Один раз при первом знакомстве с проектом
cd ~/dev/customer-project
uv run ctx scan .

# 2. Перед каждым серьёзным вопросом к Claude — обновление индекса
uv run ctx scan .

# 3. Собираешь pack по своему вопросу
uv run ctx pack . "why is the webhook retrying forever" > /tmp/ctx.md

# 4. Открываешь Claude Code в том же проекте и говоришь:
#    "Посмотри в /tmp/ctx.md — там релевантные файлы. Разберись, почему webhook retry не останавливается."
```

Claude получает точечный контекст, а не вынужден читать весь репо. Работает особенно хорошо для больших legacy-проектов, где без карты символов LLM просто заблудится.

### Для edit задач

```bash
uv run ctx pack . "add pagination to the products list endpoint" --mode edit > /tmp/edit.md
# Затем Claude'у: "Сделай правки по /tmp/edit.md. Следуй edit discipline из pack."
```

Edit-mode pack уже содержит напоминание про тесты и конфиги — Claude получает это напоминание явно, меньше шанс, что забудет обновить тест.

---

## 6. Что LV_DCP НЕ умеет (Phase 1 ограничения)

Честный список того, чего сейчас **нет**, чтобы ты не ждал этого:

### 🟡 Только Python + базовые форматы
Python (через stdlib `ast`) + Markdown + YAML + JSON + TOML — всё. TypeScript/JavaScript, Go, Rust, Java, SQL — Phase 5+. Если у тебя TS-проект, LV_DCP проиндексирует только markdown и json, что даст крайне ограниченную пользу.

### 🟡 Нет semantic / vector search
Запрос должен содержать ключевые слова, которые **буквально** есть в именах символов или содержимом файлов. Работает:
- «authentication middleware» → найдёт файлы со словами auth, middleware
- «refresh token» → найдёт refresh, token, refresh_token, RefreshToken

Не работает:
- «доменная логика безопасности» (русский не индексируется)
- «the thing that checks permissions» (слишком абстрактно)
- «security stuff» (семантический поиск нужен, а его нет)

Vector search + embeddings — **Phase 2**. Сейчас покрытие обеспечивается хорошим naming'ом в проекте и тем, что pack использует token stemming + stopword filtering.

### 🟡 Нет cross-file call graph для Python
LV_DCP видит:
- `imports` (import/from-import)
- `defines` (какой файл определяет какой символ)
- `same_file_calls` (вызовы внутри одного файла)

Не видит:
- «кто вызывает `User.save()` из другого файла» — статически неразрешимо в Python без type inference
- «какие тесты косвенно покрывают этот handler через fixture» — требует анализа pytest collection

Это сознательное решение конституции: вместо ненадёжных heuristics мы строим то, что можем сделать **детерминированно**. Phase 2+ добавит semantic analysis через Pyright/Jedi для более точного cross-file графа.

### 🟡 Нет LLM-саммари
`.context/project.md` и `symbol_index.md` — это **статистика и списки**, а не «прочитай это и поймёшь, что делает проект». Саммари уровня «этот файл реализует refresh token flow в три шага» — **Phase 2** (Claude API с content-hash кэшем, бюджет $0.50 на initial scan 500 файлов).

### 🟡 Single project
Сейчас каждый `ctx scan` работает над одним проектом. Нет «найди паттерн X во всех моих 25 репозиториях». Cross-project pattern search — **Phase 5+**.

### 🟡 Manual re-scan, никакого watcher'а
После каждой правки файла нужно руками запустить `ctx scan` заново. Никакого автоматического reindex'а через fsnotify/FSEvents. File watcher + launchd daemon — **Phase 3**.

### 🟡 Нет backend'а / нет persistence между машинами
Индекс живёт в `.context/` каждого проекта, локально. Нет central Postgres'а, нет Qdrant'а, нет API, нет sharing'а между разработчиками. Backend + Postgres + Qdrant + multi-project registry — **Phase 3+**.

### 🟡 Нет интеграции с IDE
Сейчас LV_DCP — только CLI. VS Code extension, Cursor plugin, JetBrains plugin — **Phase 6+** (если вообще). Но так как `ctx pack` выдаёт чистый markdown, его удобно вставлять в любой LLM-интерфейс вручную.

---

## 7. Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| `ctx pack` → «no cache at …» | Проект ещё не сканирован | Запусти `ctx scan <path>` сначала |
| `ctx pack` → «no fts.db …» | Старый кэш без FTS | `rm -rf .context && ctx scan <path>` |
| `scan` говорит «warn: parse error» | Парсер наткнулся на невалидный файл | Ничего — этот файл пропускается, остальные обрабатываются |
| `scan` сказал «RuntimeError: schema version N, expected M» | Кэш создан старой версией LV_DCP | `rm -rf .context && ctx scan <path>` |
| `pack` возвращает мало / плохие файлы | Запрос слишком абстрактный или файлы не в поддерживаемых языках | Переформулируй запрос под ключевые слова из кода; `ctx inspect .` покажет language breakdown |
| `scan` жалуется на permission denied | Файлы без read-доступа | LV_DCP пропускает такие файлы с warning'ом; fix'и права на файлы или добавь путь в ignore |
| В pack попадают файлы из `.venv` / `node_modules` | Рядом с project root лежит что-то нестандартное | Проверь default ignore правила в `libs/core/paths.py`; кастомные patterns — Phase 2 |

---

## 8. Что дальше — roadmap фаз

| Фаза | Что добавляется | Оценка |
|---|---|---|
| **Phase 1** (готова) | Deterministic CLI: scan / pack / inspect; Python + md/yaml/json/toml; SQLite + FTS5; edit packs | ✅ |
| **Phase 2** | LLM summaries через Claude API с content+prompt hash кэшем; vector search через sqlite-vss или pgvector; multi-stage retrieval с rerank; cross-file references v1 | ~3-4 недели |
| **Phase 3** | FastAPI backend на docker-vm, Postgres + Alembic, launchd desktop daemon через watchdog/FSEvents, multi-project registry, incremental auto-reindex | ~3-4 недели |
| **Phase 4** | Edit pack v2 с настоящим impact analysis через граф; guardrails для LLM-правок (write_protected_paths, impact checks); git intelligence (hotspots, co-change, diff summaries) | ~2-3 недели |
| **Phase 5** | Qdrant (если метрики Phase 2 упрутся в потолок); TypeScript / Go / Rust парсеры поштучно; cross-project pattern search | open-ended |
| **Phase 6** | VS Code extension, MCP server exposure, Obsidian vault sync, admin web UI | по запросу |

Phase-gated thresholds для retrieval quality проверяются в eval harness на каждом PR — см. [docs/adr/002-eval-harness.md](adr/002-eval-harness.md).

---

## 9. Внутренние документы (для любопытных)

- **[docs/constitution.md](constitution.md)** — 12 неизменяемых правил проекта
- **[docs/adr/](adr/)** — принятые архитектурные решения (budgets, eval harness, single-writer model)
- **[docs/tz.md](tz.md)** — исходное ТЗ (1842 строки, справочник)
- **[docs/dogfood/phase-1.md](dogfood/phase-1.md)** — отчёт о dogfood-прогоне Phase 1 на самом LV_DCP
- **[CLAUDE.md](../CLAUDE.md)** — инструкции для Claude-сессий в этом репо
- **`docs/superpowers/plans/`** — планы фаз с bite-sized задачами

---

## 10. Итог в одной строке

> **`ctx scan` + `ctx pack "твой вопрос"`** — получи в 10× меньше токенов в 3× быстрее при работе Claude Code с большим проектом. Всё остальное — надстройка над этим.

**Дальнейшие вопросы или баги** — напиши в issue, прикрепи `ctx inspect` output своего проекта и конкретный запрос, который не работает.
