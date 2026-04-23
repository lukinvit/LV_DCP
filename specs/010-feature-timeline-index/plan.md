# Implementation Plan: Symbol Timeline Index

**Branch**: `spec-010-feature-timeline-index` | **Date**: 2026-04-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/010-feature-timeline-index/spec.md`

## Summary

Расширить существующий инкрементальный скан-пайплайн символьным таймлайном: на каждом скане diff-ать предыдущий AST-снэпшот с текущим, эмитить `added/modified/removed/renamed/moved` события в append-only SQLite-стор (зеркалящий шаблон `libs/scan_history/store.py`), привязывать события к `commit_sha` через **пять слоёв hooks** (scan / git / release / mcp / observability), публиковать четыре новых MCP-инструмента (`lvdcp_when`, `lvdcp_removed_since`, `lvdcp_diff`, `lvdcp_regressions`). Цель — 15× экономия токенов на темпоральных запросах.

## Technical Context

**Language/Version**: Python 3.12 (async-first)

**Primary Dependencies**:
- `sqlite3` (stdlib) — event store
- `subprocess` (stdlib) — `git log`, `git for-each-ref --sort=-taggerdate`
- Ничего нового не тянем в prod — переиспользуем уже существующий стек `libs/gitintel/`, `libs/scan_history/`, `libs/scanning/`.
- Опционально: `watchfiles` (если спек #4 лендится) для tag-watcher — иначе polling каждые 60 с.

**Storage**:
- SQLite `~/.lvdcp/symbol_timeline.db` — events + snapshots + rename edges.
- Существующий `.context/cache.db` получает колонку `last_scan_commit_sha` и blob `ast_snapshot_blob` (миграция через встроенный bootstrap `ProjectIndex`, не Alembic — агент локальный).
- Postgres **не участвует** в MVP (аналогично scan_history).

**Testing**: pytest-asyncio; фикстура `tmp_git_repo` (создаёт минимальный git с коммитами/тэгами), `memory_timeline_sink` для юнит-тестов; integration — реальный git subprocess.

**Target Platform**: macOS (dev), Linux (prod); Windows — out of scope (git доступ, но launchd-hooks нерелевантны).

**Project Type**: Library (`libs/symbol_timeline/`) + CLI (`apps/cli/commands/timeline.py`) + MCP tools (`apps/mcp/tools.py` extension).

**Performance Goals**:
- Incremental scan overhead ≤ 10 % (SC-003).
- `lvdcp_when` p95 ≤ 50 ms (SC-002).
- Release snapshot ≤ 500 ms для 5k символов (SC-004).

**Constraints**:
- ADR-003 — timeline-стор пишет только agent (single writer); backend/MCP лишь читают.
- ADR-001 — SQLite ≤ 200 MB для 100k символов × 10 событий; retention-prune опционален.
- Privacy — `author` маскируется в `privacy_mode=strict` (см. spec FR-010 и libs/policies).
- Git bin должен быть в PATH (уже требование проекта).

**Scale/Scope**:
- Референс — LV_DCP ~5k символов, Phase 6 done, ~300 коммитов.
- Верхняя граница — корпоративный монорепо 100k символов, 10k коммитов, 100 тэгов.

## Constitution Check

*GATE: Must pass before Phase 0 research.*

- [x] **ADR-003 Single-writer** — agent пишет в timeline store, backend/MCP читают. Conflict-free.
- [x] **ADR-001 budgets** — SC-001 прямо бьёт по цели «снижать токены». Storage budget в Constraints.
- [x] **ТЗ §15 async везде** — timeline-sink async-совместим через `asyncio.to_thread(sqlite_call)`; scanner уже идёт по этой модели.
- [x] **ТЗ §16 edit-guard** — добавляются новые модули, существующие scanner-функции расширяются за счёт hook-callback, не переписываются. Impact analysis покроет.
- [x] **Privacy** — author маскируется по policy; timeline **не** экспортирует raw-код, только метаданные (symbol_id, event_type, sha).

**Re-check после Phase 1**: размер `ast_snapshot_blob` в `.context/cache.db`. Если > 50 MB — вынести snapshot в отдельный файл `.context/snapshots/<sha>.msgpack`.

## Project Structure

### Documentation (this feature)

```text
specs/010-feature-timeline-index/
├── plan.md              # This file
├── spec.md              # Done
├── research.md          # Phase 0 — git --follow vs content-hash similarity; tag-watcher approaches
├── data-model.md        # Phase 1 — SQLite schema, AST snapshot format, rename-edge semantics
├── quickstart.md        # Phase 1 — `ctx timeline enable`, `ctx timeline reconcile`
├── hooks.md             # Phase 1 — full hook matrix (5 layers × events × triggers)
├── contracts/
│   ├── sinks.pyi        # TimelineSink Protocol stub
│   └── mcp_tools.pyi    # lvdcp_when/_removed_since/_diff/_regressions response types
└── tasks.md             # Phase 2 — /speckit.tasks output
```

### Source Code (repository root)

```text
libs/symbol_timeline/           # NEW
├── __init__.py
├── store.py                    # Append-only SQLite event store (mirrors scan_history/store.py)
├── sinks.py                    # TimelineSink Protocol + SqliteTimelineSink + MemoryTimelineSink
├── differ.py                   # AST diff: previous snapshot × current → events
├── rename_detect.py            # Content-hash similarity + git --follow
├── snapshot.py                 # Release snapshot build + checksum
├── reconcile.py                # Mark orphaned events after history rewrite
└── query.py                    # Read-side API used by MCP tools

libs/gitintel/
├── tag_watcher.py              # NEW — polls `git for-each-ref` every N seconds; emits on new tag
└── history.py                  # MODIFY — add `commit_exists(sha)` helper for reconcile

libs/scanning/
└── scanner.py                  # MODIFY — wire TimelineSink hooks around incremental run

libs/project_index/
└── store.py                    # MODIFY — add `ast_snapshot_blob` column + `last_scan_commit_sha`

apps/agent/
└── daemon.py                   # MODIFY — wire tag_watcher into the debounce loop (optional)

apps/cli/commands/
└── timeline.py                 # NEW — ctx timeline {enable, status, reconcile, prune, backfill}

apps/mcp/
├── tools.py                    # MODIFY — add 4 new tool handlers
└── server.py                   # MODIFY — register 4 new tools

libs/core/
└── projects_config.py          # MODIFY — add TimelineConfig(enabled, retention_days, privacy_mode, ...)

tests/
├── unit/symbol_timeline/
│   ├── test_store.py
│   ├── test_differ.py
│   ├── test_rename_detect.py
│   ├── test_snapshot.py
│   └── test_reconcile.py
├── unit/gitintel/
│   └── test_tag_watcher.py
├── unit/mcp/
│   └── test_timeline_tools.py
├── integration/timeline/
│   ├── test_hooks.py           # US4 — end-to-end scan→event→query
│   ├── test_removed_since.py   # US1
│   ├── test_when.py            # US2
│   └── test_diff.py            # US3
└── perf/
    └── test_scan_with_timeline.py  # SC-003 overhead check
```

## Hook Matrix

Это сердце фичи — явная carta всех точек внедрения. Один hook = одно **стандартизированное API**, одна причина выстрелить.

### Layer 1 — Scan hooks (in-process, always-on)

Встраиваются в `libs/scanning/scanner.py:scan_project()`. Вызывают зарегистрированных sinks (`TimelineSink` protocol).

| Hook | When | Payload | Guarantees |
|------|------|---------|------------|
| `on_scan_begin(project_root, commit_sha, started_at)` | перед AST-diff | — | вызывается ровно 1 раз, даже на пустом скане |
| `on_added(symbol_id, file_path, content_hash, commit_sha)` | символ есть сейчас, не было раньше | — | idempotent per-(symbol_id, commit_sha) |
| `on_modified(symbol_id, old_hash, new_hash, commit_sha)` | content_hash изменился | — | skip при одинаковом hash (no-op event не эмитим) |
| `on_removed(symbol_id, last_seen_sha, removed_at_sha)` | был раньше, нет сейчас | — | может объединяться с `on_renamed` — scanner вызывает только один из двух |
| `on_renamed(old_symbol_id, new_symbol_id, confidence, commit_sha)` | rename_detect вернул confidence ≥ 0.85 | — | взаимоисключимо с (on_removed + on_added) для пары символов |
| `on_moved(symbol_id, old_path, new_path, commit_sha)` | same content_hash, другой файл | — | отдельный event_type, НЕ trigger-ит modified |
| `on_scan_end(project_root, commit_sha, stats)` | после всех per-symbol emit-ов | stats: `{added: n, removed: n, ...}` | закрывает транзакцию каждого sink-а; вызывается даже при исключении в середине |

**Registration**: `scanner.register_timeline_sink(sink: TimelineSink)`. Множественная регистрация поддерживается (fan-out).

### Layer 2 — Git hooks (optional, latency booster)

Опциональные Claude Code hooks (`.claude/hooks/*.sh`), снижают задержку «событие → индекс» с ~2 с debounce до <200 мс. **НЕ** native `.git/hooks/*` — пользователь может не хотеть трогать свой git.

| Hook | Trigger | Action |
|------|---------|--------|
| `post-commit.sh` | после `git commit` | вызывает `ctx scan <project> --incremental --commit-sha $(git rev-parse HEAD)` |
| `post-merge.sh` | после `git merge` / `git pull` | то же + фоновый `ctx timeline reconcile` если `MERGE_HEAD` существовал |
| `post-checkout.sh` | после `git checkout` (branch switch) | **не** эмитит events — только синкает `last_scan_commit_sha`; timeline события рождаются только на реальных изменениях, не на смене указателя |
| `post-rewrite.sh` | после `git rebase` / `commit --amend` | триггерит `ctx timeline reconcile` с `orphaned=true` на отсохших SHA |

Все четыре — опциональные. Дефолт пайплайн (без git-hooks) работает через debounce-скан.

### Layer 3 — Release hooks (tag watcher)

`libs/gitintel/tag_watcher.py` — лёгкий polling loop в daemon-е. Каждые 60 с запускает `git for-each-ref --sort=-taggerdate refs/tags --format='%(refname:short) %(objectname)'`, сравнивает с `known_tags_set`, на новых — эмитит `on_release(tag, head_sha, timestamp)`.

| Hook | Trigger | Action |
|------|---------|--------|
| `on_release(tag, head_sha, timestamp)` | новый git tag | вызывает `libs/symbol_timeline/snapshot.build_snapshot(tag, head_sha)` → immutable `symbol_timeline_snapshots` запись + копия AST-снэпшота |
| `on_tag_invalidated(old_tag, old_head_sha, new_head_sha)` | тэг с тем же именем, но другим SHA | старый snapshot помечается `tag_invalidated=true`, создаётся новый |

Если спек #008 shadow-git-checkpoints лендится — tag_watcher подписывается и на checkpoint-refs с параметром `ref_kind="shadow_checkpoint"`.

### Layer 4 — MCP hooks (query-side enrichment)

Встраиваются в pipeline `lvdcp_pack`. Гейтятся `EmbeddingConfig.enable_timeline_enrichment` (дефолт `True`).

| Hook | Trigger | Action |
|------|---------|--------|
| `pre_pack_enrich(query, mode)` | query содержит маркер (`когда`, `since v`, `removed`, `when was`, `между v`, ...) | добавляет в pack топ-N relevant timeline events для упомянутых символов |
| `post_pack_annotate(pack, events)` | pack уже построен | секция `## Timeline facts` с 1–3 KB ранжированных событий |

Маркеры — configurable через `TimelineConfig.pack_enrichment_markers: list[str]`.

### Layer 5 — Observability hooks (telemetry)

Через структурированный лог + Prometheus метрики. Всегда включены.

| Metric | Type | Labels | Sampled at |
|--------|------|--------|-----------|
| `symbol_timeline_events_total` | counter | `event_type`, `project_root` | каждый `on_*` emit |
| `symbol_timeline_query_latency_seconds` | histogram | `tool` ∈ `{when, removed_since, diff, regressions}` | каждый MCP call |
| `symbol_timeline_snapshot_build_seconds` | histogram | `tag_kind` ∈ `{git_tag, shadow_checkpoint}` | каждый `on_release` |
| `symbol_timeline_reconcile_orphaned_total` | counter | `project_root` | каждый reconcile run |
| `symbol_timeline_sink_errors_total` | counter | `sink_name`, `event_type` | on sink exception |

Логи — структурно через structlog с полями `project_id`, `scan_id`, `commit_sha`, `event_type`, `symbol_id`, `duration_ms`.

## Phases

### Phase 0 — Research (before code)

Артефакт `research.md`:

1. **Rename detection**: git `--follow` vs content-hash similarity (SimHash / MinHash) — matrix accuracy / performance.
2. **AST snapshot storage**: blob в SQLite vs отдельные msgpack-файлы — break-even по размеру индекса.
3. **Tag watcher patterns**: polling каждые 60 с vs `git --refresh` hook — latency/cost trade-offs.
4. **Privacy surface**: маскирование author email-а — хэширование vs pseudonym pool.

### Phase 1 — Design

Артефакты `data-model.md`, `quickstart.md`, `hooks.md`, `contracts/`:

1. Финальная SQLite схема `symbol_timeline` с 3 таблицами (`events`, `snapshots`, `rename_edges`) + индексами.
2. `TimelineSink` Protocol финальный API + reference implementations.
3. MCP tool contracts — Pydantic response models для 4 новых tools.
4. `hooks.md` — full matrix из plan.md + детали registration API.
5. Quickstart — `ctx timeline enable` + env `LVDCP_TIMELINE__ENABLED=1` (pydantic-settings).

### Phase 2 — Implementation

См. `tasks.md` (будет сгенерирован `/speckit.tasks`). Ориентировочное разбиение:

- **US1 flow (P1)** — store + differ + `lvdcp_removed_since` tool. Standalone testable.
- **US2 flow (P2)** — `lvdcp_when` tool over same store.
- **US3 flow (P3)** — `lvdcp_diff` + release snapshots + tag watcher.
- **US4 flow (P1, hooks)** — full scan integration + Claude Code hooks + reconcile.

### Phase 3 — Validation

- Synthetic git repo-based integration tests для US1/2/3/4 (SC-001, SC-005).
- Perf bench `tests/perf/test_scan_with_timeline.py` для SC-003.
- Snapshot size check на LV_DCP самом для SC-004.
- Manual exercise на реальной истории LV_DCP: `lvdcp_diff(v0.5.0, v0.6.1)` — глазами проверить что diff разумен.

## Risks & Mitigations

| Риск | Impact | Mitigation |
|------|--------|-----------|
| Rename detection выдаёт false-positives | M | Confidence threshold ≥ 0.85 + spec FR-007: low confidence → два отдельных события с флагом `rename_candidate`. Пользователь может пересмотреть через `ctx timeline review-renames`. |
| AST snapshot blob раздувает `.context/cache.db` | M | Phase 1 re-check; план B — вынести snapshots в `.context/snapshots/<sha>.msgpack` с GC по retention. |
| Tag watcher пропускает тэги (polling lag) | L | Acceptable — snapshot может быть создан с лагом до 60 с, timestamp фиксирует **момент обнаружения**, а не `git tag`. Для real-time юз-кейса — opt-in Claude Code hook `post-tag.sh`. |
| Reconcile после rebase не находит «правильный» новый SHA | M | Не пытаемся re-link orphaned events к новым SHA. Помечаем `orphaned=true`, пользователь может запустить `ctx timeline backfill --since <old-sha>` для пере-capture. |
| Privacy leak: author email в timeline | H | `privacy_mode=strict` → `author_hash = sha256(email)[:12]`. Default `balanced` — email хранится локально, не экспортируется в MCP-ответах без явного `include_author=true`. |
| Первичная заливка legacy-истории долгая | L | Out of scope в MVP. Опциональная `ctx timeline backfill --since <sha>` работает в фоне с чекпоинтами. |
| Sinks падают и теряют события | M | `on_scan_end` в try/finally; sink-errors считаются в метрику, не блокируют scanner; при 3 подряд failures sink автоматически disable-ится с warning. |

## Configuration knobs (timeline)

Живут в `EmbeddingConfig` / новом `TimelineConfig` (см. `libs/core/projects_config.py`).

| Поле | Тип | Дефолт | Назначение |
|------|-----|--------|-----------|
| `timeline.enabled` | bool | `True` | master switch |
| `timeline.store_path` | Path | `~/.lvdcp/symbol_timeline.db` | SQLite-файл |
| `timeline.retention_days` | int \| None | `None` | `None` = хранить всё; иначе prune старше N дней |
| `timeline.privacy_mode` | Literal | `"balanced"` | `strict` хэширует author; `balanced` хранит email; `off` отключает author совсем |
| `timeline.rename_similarity_threshold` | float | `0.85` | ниже — два отдельных события с `rename_candidate` |
| `timeline.enable_timeline_enrichment` | bool | `True` | pack enrichment hook (Layer 4) |
| `timeline.pack_enrichment_markers` | list[str] | `["когда", "when was", "since v", "removed", "между v"]` | query markers, case-insensitive |
| `timeline.tag_watcher_poll_seconds` | int | `60` | частота polling-а |
| `timeline.sink_plugins` | list[str] | `[]` | import-paths custom sinks (Obsidian, PagerDuty, etc.) |

## Interaction with other specs

- **#004 watchfiles** — tag_watcher может подписаться на FSEvents через watchfiles вместо polling (нативная latency ~10 мс).
- **#005 gitleaks/detect-secrets** — timeline не должен логировать символы, помеченные как secret (respect `privacy_mode`, exclude фильтр по tag).
- **#008 shadow-git-checkpoints** — release hook слушает и shadow-refs; `ref_kind` различает в snapshot-е.
- **#002 reranker** — pack enrichment (Layer 4) подаёт timeline events в pool для реранкинга наравне с кодом.

## Out of Scope

- Cross-repo timeline (символ мигрировал между проектами).
- UI/dashboard — MCP-tools хватает для MVP.
- PR/issue enrichment (GitHub API) — отдельная надстройка поверх TimelineSink.
- Legacy backfill как MVP-требование — только опциональный CLI.
- Windows — no launchd, hooks работают руками.
