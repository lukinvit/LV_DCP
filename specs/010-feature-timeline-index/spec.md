# Feature Specification: Symbol Timeline Index

**Feature Branch**: `spec-010-feature-timeline-index`
**Created**: 2026-04-22
**Status**: Draft
**Input**: Pain observed by maintainer — после релиза в смежном проекте исчезли фичи; чтобы найти, когда и в каком коммите их реализовали, LLM-агент тратит 100–500 KB токенов на git log + diff walk. Цель: сделать «когда реализовано / что пропало после релиза» индексным lookup на 1–5 KB.

## User Scenarios & Testing

### User Story 1 — «Что пропало после релиза Y?» (Priority: P1)

Мейнтейнер видит регрессию после выхода `v0.6.1`. Хочет одним запросом получить список символов, которые существовали в `v0.6.0` и отсутствуют в HEAD (или в `v0.6.1`), с указанием commit-а удаления и автора.

**Why this priority**: это точный триггер для запроса пользователя — самый дорогой кейс в текущем воркфлоу. Без него агент обязан идти в `git log --all -S "<name>"` на каждый подозрительный символ.

**Independent Test**: в `tests/integration/timeline/test_removed_since.py` создаётся синтетический git-репо: 3 тэга (`v1`, `v2`, `v3`), между ними символы добавляются и удаляются. `lvdcp_removed_since(ref="v1")` возвращает ровно ожидаемый набор с корректными commit_sha и timestamp. Метрика: Recall = 1.0, Precision = 1.0, ответ ≤ 2 KB JSON.

**Acceptance Scenarios**:

1. **Given** проект с таймлайн-индексом и тэгом `v0.6.0`, **When** `lvdcp_removed_since(ref="v0.6.0")`, **Then** каждый удалённый символ содержит `symbol_id`, `file_path`, `last_seen_sha`, `removed_at_sha`, `removed_at_timestamp`, `author`.
2. **Given** ref, которого нет в репо, **When** запрос, **Then** respond `{error: "ref_not_found", ref: ...}` без стэктрейса.
3. **Given** символ был переименован (не удалён), **When** запрос, **Then** он **не** попадает в removed — попадает в отдельный `renamed` список с `renamed_to`.

---

### User Story 2 — «Когда был реализован символ X?» (Priority: P2)

Разработчик видит упоминание функции `embed_batch_multi` в логе и хочет понять, когда она появилась, в каком коммите, из какого PR. Сегодня: `git log --all -S "embed_batch_multi"` + чтение каждого diff. Цель: один вызов → полный timeline символа.

**Why this priority**: второй по частоте запрос пользователя. Блокер для refactor-плана («надо понять историю прежде чем менять»).

**Independent Test**: `tests/integration/timeline/test_when.py` — корпус с символами, добавленными/изменёнными/переименованными на разных коммитах. `lvdcp_when(symbol="libs.embeddings.adapter.embed_batch_multi")` возвращает хронологический список событий. Метрика: для каждого события совпадает `commit_sha` и `event_type`; ответ ≤ 3 KB.

**Acceptance Scenarios**:

1. **Given** символ с полной историей (added → modified × 3 → renamed), **When** запрос, **Then** ответ содержит `events: [{event_type, commit_sha, timestamp, author, content_hash}, ...]` в хронологическом порядке.
2. **Given** символ только что добавлен (один коммит), **When** запрос, **Then** один event с `event_type="added"`.
3. **Given** символа нет в индексе, **When** запрос, **Then** `{error: "symbol_not_found", candidates: [...ranked top-5 по substring...]}`.

---

### User Story 3 — «Diff между релизами» (Priority: P3)

Product owner готовит release notes и хочет увидеть структурный diff: что добавлено / удалено / изменено / переименовано между `v0.6.0` и `v0.7.0` на уровне символов, а не строк кода.

**Why this priority**: дешёвая надстройка над US1 + timeline. Одновременно закрывает кейс «что поменялось за спринт».

**Independent Test**: `tests/integration/timeline/test_diff.py` — два тэга с известным diff. `lvdcp_diff(from="v0.6.0", to="v0.7.0")` возвращает четыре списка (`added`, `removed`, `modified`, `renamed`). Метрика: точное совпадение множеств, ответ ≤ 5 KB даже для крупных diff-ов (ранжируется по importance).

**Acceptance Scenarios**:

1. **Given** два тэга, **When** `lvdcp_diff(from, to)`, **Then** структура `{added: [...], removed: [...], modified: [...], renamed: [...]}` с suffix top-N per category и пагинацией.
2. **Given** `from == to`, **When** запрос, **Then** все списки пустые, ответ ≤ 200 B.
3. **Given** `to="HEAD"`, **When** запрос, **Then** используется текущий HEAD, timestamp фиксируется в ответе.

---

### User Story 4 — «Хуки для автоматической фиксации» (Priority: P1)

Таймлайн бесполезен без пайплайна, который его пишет. Нужен набор **hooks** (git, scan, release, MCP), которые гарантируют: каждое изменение AST, каждый коммит и каждый тег оставляют событие в timeline-стор без явных ручных действий.

**Why this priority**: **без этого всё остальное не работает**. Пользователь явно подчеркнул: «точно надо хуки предусмотреть».

**Independent Test**: `tests/integration/timeline/test_hooks.py` — создаёт git-репо, запускает `ctx scan`, делает коммит, запускает `ctx scan` снова. Проверяет: в `symbol_timeline` появились события `added/modified/removed` с корректным `commit_sha == HEAD` на момент каждого скана. Без ручных вызовов.

**Acceptance Scenarios**:

1. **Given** чистый репо + агент запущен, **When** пользователь создаёт файл с новым символом и коммитит, **Then** debounced инкрементальный скан + timeline emit → событие `added` с `commit_sha == post-commit HEAD`.
2. **Given** удалён коммитом файл, **When** скан триггерится (debounced или post-commit hook), **Then** все символы файла получают событие `removed`.
3. **Given** `git tag v1.0.0`, **When** tag watcher фиксирует новый тэг, **Then** создан release-snapshot с `tag="v1.0.0"`, `head_sha=...`, без лишних event-ов.
4. **Given** rebase / force-push переписал историю, **When** timeline-reconcile hook запускается, **Then** ранее записанные события с «осиротевшими» `commit_sha` помечаются `orphaned=True`, не удаляются, покрываются отчётом.

---

### Edge Cases

- **Переименование vs delete+add**: используется git `--follow` + content-hash similarity ≥ 0.85. При меньшей уверенности — два события (`removed`, `added`), флаг `rename_candidate=true`, пара ссылается друг на друга.
- **Move файла**: отдельный event_type `moved`, `old_path`/`new_path`, не трактуется как delete+add.
- **Перезапись истории (rebase/force-push)**: timeline-reconcile hook (см. US4.4) помечает события, чьи `commit_sha` не существуют в `git reflog`, как `orphaned`. **Никогда** не удаляет — только отмечает.
- **Приватные символы** (`_internal`, dunder): включаются в индекс с `visibility="private"`, по дефолту скрыты из MCP-ответов (фильтр `include_private=False`).
- **Два символа с одинаковым именем в разных модулях**: `symbol_id = sha256(project_id|file_path|qualified_name|kind)`, коллизий нет.
- **Tag без коммита (`git tag -d` и пере-создание)**: snapshot пересоздаётся с новым `snapshot_id`, старый помечается `tag_invalidated=true`.
- **Mono-repo с несколькими git-родителями**: timeline-capture работает на уровне `project_root`, границы определяются по ближайшему `.git`.
- **Bad ref в запросе**: не raise — возвращать `{error: "ref_not_found"}`.

## Requirements

### Functional Requirements

- **FR-001**: Система MUST предоставлять `libs/symbol_timeline/store.py` — append-only SQLite event-стор с схемой `symbol_timeline_events(id, project_root, symbol_id, event_type, commit_sha, timestamp, author, content_hash, file_path, extra_json, orphaned)`, по дизайну аналогичный `libs/scan_history/store.py`.
- **FR-002**: Scan-пайплайн (`libs/scanning/scanner.py`) MUST эмитить timeline-события через pluggable интерфейс `TimelineSink` — при каждом инкрементальном run-е сравнивает предыдущий AST-снэпшот с текущим и вызывает `sink.on_added / on_modified / on_removed / on_renamed / on_moved`.
- **FR-003**: `TimelineSink` — формальный Protocol в `libs/symbol_timeline/sinks.py`; минимум две реализации: `SqliteTimelineSink` (дефолт) и `MemoryTimelineSink` (для тестов). Протокол позволяет подключать дополнительные sinks без изменений scanner-а.
- **FR-004**: `post_scan_hook(project_root, commit_sha)` MUST вызываться scanner-ом ровно один раз за скан после всех per-symbol event emit-ов — даже на пустом скане, для закрытия транзакции sink-ов.
- **FR-005**: Release-boundary snapshot — при обнаружении нового git-тэга через `libs/gitintel/tag_watcher.py` (NEW) MUST создать immutable запись в `symbol_timeline_snapshots(tag, head_sha, timestamp, symbol_count, checksum)` + копию актуального AST-снэпшота.
- **FR-006**: MCP-сервер MUST экспортировать инструменты `lvdcp_when`, `lvdcp_removed_since`, `lvdcp_diff`, `lvdcp_regressions` с строгими Pydantic-респонсами и bounded output size (≤ 20 KB на запрос, ranking по importance + recency).
- **FR-007**: Git-hooks (Claude Code, не `.git/hooks/*`) MUST быть опциональны — дефолт поведения: timeline capture работает через debounce-скан агента; hooks (post-commit, post-merge, post-tag) лишь **ускоряют** латентность «событие → индекс» с ~2 с до <200 мс, но НЕ являются обязательными.
- **FR-008**: Timeline-reconcile hook MUST запускаться на команде `ctx timeline reconcile <project>` + автоматически при обнаружении расхождения «commit в timeline ∉ git log». Помечает orphaned=True, не удаляет события.
- **FR-009**: Storage budget — append-only таблица с индексами по `(project_root, symbol_id, timestamp)` и `(project_root, commit_sha)`. Retention по дефолту — `None` (хранить всё), опциональный prune через `ctx timeline prune --older-than 365d`.
- **FR-010**: Pack-enrichment — если в query `lvdcp_pack` замечены ключевые маркеры (`когда`, `когда был`, `удалён`, `when was`, `since v`, `between v`), пайплайн MUST автоматически включать relevant timeline events в итоговый pack. Гейтится флагом `enable_timeline_enrichment` в `EmbeddingConfig` (дефолт `True`).

### Key Entities

- **TimelineEvent** — запись об изменении символа: `{symbol_id, event_type ∈ {added, modified, removed, renamed, moved}, commit_sha, timestamp, author, content_hash, file_path, extra_json}`.
- **ReleaseSnapshot** — иммутабельный слепок AST-индекса на момент тэга: `{snapshot_id, tag, head_sha, timestamp, symbol_count, checksum}` + копия AST-row-ов с `snapshot_id`-discriminator.
- **SymbolIdentity** — stable id `sha256(project_id|file_path|qualified_name|kind)`; переживает изменение содержимого и move; НЕ переживает rename (rename создаёт отдельный id, две записи связываются через `rename_edge`).
- **TimelineSink** — Protocol с методами `on_added`, `on_modified`, `on_removed`, `on_renamed`, `on_moved`, `on_scan_begin`, `on_scan_end`. Scanner вызывает всех зарегистрированных sinks внутри одной «transaction per scan».

## Success Criteria

### Measurable Outcomes

- **SC-001**: Token footprint типичного ответа на «когда был реализован X» падает с ~80 KB (git log walk) до ≤ **5 KB** (indexed lookup) — **минимум 15× экономия**.
- **SC-002**: Latency `lvdcp_when(symbol)` ≤ **50 ms** p95 на индексе 50k событий (SQLite + два индекса хватает).
- **SC-003**: Timeline capture не добавляет более **10%** overhead к базовому времени инкрементального скана (измеряется в `tests/perf/test_scan_with_timeline.py`).
- **SC-004**: Release snapshot для проекта 5k символов создаётся за **≤ 500 ms** и занимает **≤ 2 MB** на диске.
- **SC-005**: `lvdcp_diff(from, to)` на paired релизах монорепо LV_DCP (`v0.5.0` → `v0.6.1`, ~200 изменённых символов) отвечает за **≤ 200 ms** и укладывается в **≤ 15 KB** ответа.
- **SC-006**: Hooks-coverage — в integration-тесте `test_hooks.py` ≥ **6 из 7** сценариев (added/modified/removed/renamed/moved/tag/reconcile) ловятся автоматически без ручных вызовов.

## Assumptions

- Git доступен как бинарь в PATH (уже требование LV_DCP).
- AST-снэпшот предыдущего скана persist-ится в существующем `.context/cache.db` — FR-002 добавляет поле `last_scan_commit_sha` и ключ `ast_snapshot_blob` в существующую схему (через миграцию).
- Размер истории ограничен разумно: для 100k символов × 10 событий × 200 B ≈ 200 MB SQLite — приемлемо. Если проект больше, активируется retention-prune.
- Пользователь не хочет переписывать git history часто; orphaned events — редкий случай, reconcile hook достаточно реактивного.
- Release granularity = git tags. Проекты без тэгов используют commit SHA напрямую (`from="HEAD~50"`).

## Dependencies & Constraints

- **Блокирует**: часть Phase 3 power-user — dashboards хотят timeline-данных; но сам timeline не зависит от спеков #1–9.
- **Зависит от**: `libs/scanning/scanner.py` (incremental), `libs/gitintel/` (extension), `libs/scan_history/` (reference impl), `libs/project_index` (AST snapshot storage).
- **Пересечения со спеком #008 shadow-git-checkpoints**: если #008 лендится раньше, его shadow-checkpoint может служить альтернативным триггером release-snapshot-ов. Дизайн нейтрален — timeline подписывается на «любое появление ref-а» и различает git-tag vs shadow-checkpoint через `ref_kind`.
- **Конституция**: ADR-003 (single-writer) — только backend/agent пишет в timeline-стор. ADR-001 budgets — 15× экономия токенов явно попадает в цель «снижать расход».
- **Privacy**: timeline содержит `author` email-ы (из git). В режиме `privacy_mode=strict` хэшировать или маскировать до анонимного `author_hash`.

## Out of Scope

- Реконструкция **legacy-истории** целого репо до момента включения timeline-пайплайна. Первичная заливка — опционально через `ctx timeline backfill --since <sha>`, не MVP.
- Кросс-репо timeline (символ мигрировал из одного проекта в другой).
- UI/дашборды — MCP tools достаточно для MVP, dashboards — Phase 3.
- Интеграция с GitHub API для подтягивания PR/issue metadata — отдельная фича, может подписаться на тот же TimelineSink.
- **Не** становимся git-log сервисом общего назначения — timeline это про **символы**, не про строки и не про diff-блоки.
