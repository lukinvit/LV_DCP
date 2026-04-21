# Feature Specification: watchfiles вместо watchdog в desktop-агенте

**Feature Branch**: `004-watchfiles-watcher`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #4 — замена `watchdog` на Rust-ядро `watchfiles` (notify-rs) с нативным async-итератором, встроенным debounce, атомарным batch событий. Фиксирует класс багов «watcher потерял событие после sleep/resume» и деградацию на monorepos 10k+ файлов.

## User Scenarios & Testing

### User Story 1 — Стабильная работа после sleep/resume (Priority: P1)

Пользователь закрывает крышку MacBook, открывает через час, правит 3 файла. Все изменения должны быть замечены — текущий watchdog теряет события в ≥50% таких кейсов.

**Why this priority**: ядро Phase 1; без этого LV_DCP даёт stale pack'и и подрывает доверие.

**Independent Test**: скрипт `tests/integration/agent/test_sleep_resume.py` эмулирует паузу event-loop и проверяет, что изменения, сделанные во время паузы, детектятся после возобновления.

**Acceptance Scenarios**:

1. **Given** агент запущен, **When** event loop приостановлен на 30 с → возобновлён → за время паузы изменены 3 файла, **Then** все 3 события зафиксированы при следующей итерации.
2. **Given** система проснулась после macOS sleep, **When** watcher возобновляется, **Then** он переинициализирует fseventsd-соединение, если нужно, без потери событий.

---

### User Story 2 — Монорепо 10k+ файлов (Priority: P1)

Разработчик индексирует репозиторий с 30 тыс файлов + 200 тыс в `node_modules`. Текущий watchdog деградирует по CPU/latency; watchfiles держит native throughput notify-rs.

**Why this priority**: реальные продовые репо легко превышают 10k файлов — без масштабируемости LV_DCP бесполезен для senior-разработчиков.

**Independent Test**: `scripts/bench_watcher.py` — эмулирует 30k файлов, 50 modifications/sec; ассертит, что CPU агента ≤ 15%, latency событий ≤ 200 мс.

**Acceptance Scenarios**:

1. **Given** 30k файлов под watch, **When** 50 изменений/сек в течение 60 с, **Then** все события получены, latency p95 ≤ 200 мс, CPU агента ≤ 15%.

---

### User Story 3 — Встроенный debounce (Priority: P2)

`awatch(step=500)` возвращает batch событий как atomic set; ручная очередь дебаунса (~200 строк) удаляется.

**Why this priority**: упрощает код агента, убирает класс багов в самописном дебаунсере.

**Independent Test**: смена одного файла 20 раз за 300 мс → один событийный батч.

**Acceptance Scenarios**:

1. **Given** файл меняется 20 раз за 300 мс, **When** `awatch(step=500)` тикает, **Then** возвращается один set с одним событием (modified file), а не 20.

---

### Edge Cases

- Watched path перестал существовать (симлинк сломан, volume unmounted) — watchfiles выкидывает ошибку, агент перезапускает watcher с бекоффом.
- Permissions denied на поддиректории — игнорируется с `agent_watcher_permission_denied_total` метрикой.
- Rename across filesystem boundaries — обрабатывается как delete+create.
- Watchfiles на Windows/Linux tested отдельно (LV_DCP targets macOS, но CI на Linux должен проходить).
- Очень большие burst (100k events) — batch splitting в агенте по chunksize ≤ 1000.

## Requirements

### Functional Requirements

- **FR-001**: Класс `apps/agent/watcher.py::FileWatcher` MUST использовать `watchfiles.awatch(path, step=500, rust_timeout=10000)` как единственный источник событий.
- **FR-002**: MUST поддерживать glob-фильтры через `watchfiles.DefaultFilter` + кастомная реализация (игнор `.git/`, `node_modules/`, `__pycache__/`, binary patterns).
- **FR-003**: События MUST маппиться на internal `FileEvent(kind: FileEventKind, path: Path, mtime_ns: int)`; `FileEventKind` = {added, modified, deleted, renamed_from, renamed_to}.
- **FR-004**: При ошибке (ConnectionError, OSError) watcher MUST рестартить итератор с exponential backoff (100мс → 5с) и инкрементить `agent_watcher_restart_total`.
- **FR-005**: При `SIGTERM`/`SIGINT` MUST корректно завершить итератор через `stop_event.set()` и await-ить дренаж in-flight events.
- **FR-006**: MUST поддерживать горячее обновление watched paths без перезапуска агента (stop → new instance).
- **FR-007**: Убрать модуль самописного debouncer'а (если есть) и его тесты — заменить на `awatch(step=...)`.
- **FR-008**: Совместимость с lvdcp-scheduler (Dramatiq): события поступают в redis-queue на ту же схему сообщений, что и сейчас.

### Key Entities

- **FileEvent** — DTO (существует). Маппится из `watchfiles.Change`.
- **WatcherFilter** — кастомный фильтр наследник `DefaultFilter`; учитывает `.gitignore`, `workspace_config.ignore_patterns`.
- **AgentWatcher lifecycle** — `start() → running → stop() → stopped`, сопоставлен с launchd lifecycle.

## Success Criteria

### Measurable Outcomes

- **SC-001**: test_sleep_resume.py ассертит 100% детекции событий после паузы; ноль потерянных событий на 100 запусков CI.
- **SC-002**: bench_watcher.py на 30k файлов: latency p95 ≤ 200 мс, CPU агента ≤ 15% (vs 40% текущий watchdog).
- **SC-003**: Кодовая база агента сокращается минимум на **150 строк** (удаление debouncer + ручного fseventsd retry).
- **SC-004**: Zero регрессий на существующих agent integration tests (все тесты проходят).
- **SC-005**: Memory агента ≤ 80 MB в idle (vs ~60 MB baseline; 20 MB запас на Rust runtime).

## Assumptions

- `watchfiles>=0.24` поддерживает macOS FSEvents натив.
- Rust-ядро (notify-rs) стабильнее watchdog на macOS (подтверждается issue tracker watchdog).
- Python 3.12 совместим (watchfiles требует 3.8+).
- На macOS 14+ launchd не конфликтует с watchfiles.
- Existing `.gitignore` парсинг (если есть) переиспользуется для `WatcherFilter`.

## Dependencies & Constraints

- Независимо от: #1–3 (embeddings), #5–9.
- Единственная точка контакта с остальным проектом — queue в redis (message schema не меняется).
- Constitution §4 (deterministic around LLM): watcher остаётся детерминированным.
- ADR-003: watcher — часть agent, backend не читает ФС.
