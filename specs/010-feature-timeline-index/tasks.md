---
description: "Task list for Symbol Timeline Index — когда был реализован X, что пропало после релиза Y"
---

# Tasks: Symbol Timeline Index

**Input**: Design documents from `specs/010-feature-timeline-index/`
**Prerequisites**: plan.md (present), spec.md (present), research.md (Phase 0), data-model.md + hooks.md (Phase 1)

**Tests**: обязательны — unit для store/differ/rename_detect, integration с реальным `git` subprocess (tmp-репо с тэгами), perf-тест для SC-003.

**Organization**: сгруппированы по user story; **US1 + US4 (hooks) — MVP**, US2/US3 — надстройки на том же сторе.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимостей)
- **[Story]**: US1/US2/US3/US4 из spec.md
- Пути абсолютные относительно репо-корня

## Path Conventions

- `libs/symbol_timeline/` — новая библиотека (store, sinks, differ, rename_detect, snapshot, query, reconcile)
- `libs/gitintel/` — extension (`tag_watcher.py`)
- `libs/scanning/scanner.py`, `libs/project_index/store.py` — modifications
- `apps/mcp/{tools,server}.py` — 4 новых tool
- `apps/cli/commands/timeline.py` — CLI
- `tests/unit/symbol_timeline/`, `tests/integration/timeline/`, `tests/perf/` — тесты

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: конфиг, фикстуры, минимальные зависимости (stdlib only).

- [x] **T001** Добавить `TimelineConfig` в `libs/core/projects_config.py`: `enabled: bool = True`, `store_path: Path`, `retention_days: int | None = None`, `privacy_mode: Literal["strict","balanced","off"] = "balanced"`, `rename_similarity_threshold: float = 0.85`, `enable_timeline_enrichment: bool = True`, `pack_enrichment_markers: list[str]`, `tag_watcher_poll_seconds: int = 60`, `sink_plugins: list[str] = []`. Валидатор порога: `0.0 ≤ threshold ≤ 1.0`.
- [x] **T002** [P] Pytest-фикстура `tmp_git_repo` в `tests/conftest.py`: создаёт временный git-репо с настроенным `user.name/email`, helper-ами `make_commit(files, message) -> sha`, `make_tag(name, sha) -> sha`, `rewrite_history(strategy)`. Нужна всем integration-тестам фазы 3–7.
- [x] **T003** [P] Pytest-фикстура `memory_timeline_sink`: in-memory реализация `TimelineSink` с публичным `.events: list[TimelineEvent]` для unit-ассертов. Один из двух reference-sink-ов в FR-003.
- [x] **T004** Добавить параметр `--timeline-enabled/--no-timeline-enabled` в `ctx scan` CLI (дефолт из `TimelineConfig.enabled`). Без флага поведение скана не меняется — backward-compatible.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: сторы, протокол sink-ов, differ, rename_detect — без этого ни один user story не заработает.

- [x] **T005** `libs/symbol_timeline/store.py`: SQLite схема (`events` + `snapshots` + `rename_edges`) + `append_event(store, event)` + `events_for_symbol(store, project_root, symbol_id)` + `events_between(store, project_root, from_ref, to_ref)` + retention prune. **Зеркалит** шаблон `libs/scan_history/store.py`: WAL, lazy connect, env-overridable path через `LVDCP_TIMELINE_DB`.
- [x] **T006** `libs/symbol_timeline/sinks.py`: `TimelineSink` Protocol (7 методов: `on_scan_begin`, `on_added`, `on_modified`, `on_removed`, `on_renamed`, `on_moved`, `on_scan_end`) + `SqliteTimelineSink` (wraps store из T005) + `MemoryTimelineSink` (for tests). FR-003.
- [x] **T007** [P] `libs/symbol_timeline/differ.py`: `diff_ast_snapshots(prev: AstSnapshot, curr: AstSnapshot, commit_sha: str) -> Iterator[TimelineEvent]`. Чистая функция, без I/O. Возвращает строго упорядоченные `added/modified/removed` до того, как rename_detect их объединит.
- [x] **T008** [P] `libs/symbol_timeline/rename_detect.py`: `pair_renames(events, *, similarity_threshold=0.85, git_follow=True) -> tuple[list[RenameEdge], list[TimelineEvent]]`. Принимает поток `added + removed` от differ-а, возвращает (rename_edges, оставшиеся_events). Использует `git log --follow` когда пути в одном репо; fallback — content-hash SimHash/MinHash (см. research.md).
- [x] **T009** Unit-тесты `tests/unit/symbol_timeline/`:
  - `test_store.py` — append + query + retention + WAL concurrency (два writer-а, один выигрывает)
  - `test_differ.py` — 12+ сценариев (added, modified, removed, unchanged, empty-prev, empty-curr)
  - `test_rename_detect.py` — high/low confidence, пары vs одиночные
  - `test_sinks.py` — protocol conformance обоих reference-sink-ов
- [x] **T010** **Checkpoint**: `pytest tests/unit/symbol_timeline -q` зелёный; всё foundational API стабильно.

---

## Phase 3: Scan Integration (US4 — scan-level hook, Priority: P1)

**Goal**: scanner эмитит timeline-события автоматически на каждом инкрементальном run-е. **Это — главная hook-интеграция (Layer 1)**; без неё US1/US2/US3 не имеют данных.

**Independent Test**: `tests/integration/timeline/test_hooks.py` — создать git-репо с символами, прогнать `ctx scan` дважды (с изменениями между), проверить, что `symbol_timeline.db` содержит правильные события с корректными `commit_sha`.

- [x] **T011** [US4] Расширить `libs/project_index/store.py`: колонки `last_scan_commit_sha TEXT` и `ast_snapshot_blob BLOB` (msgpack). Schema migration в существующем bootstrap (не Alembic — `.context/cache.db` локальный). Тест: старая БД открывается, миграция применяется, данные не теряются.
- [x] **T012** [US4] Wire hooks в `libs/scanning/scanner.py`: `register_timeline_sink(sink)` class-level реестр + вызовы `on_scan_begin` / per-symbol `on_*` / `on_scan_end` в `scan_project()`. `on_scan_end` в `finally`, чтобы транзакция sink-а закрывалась даже при exception. Idempotent: скан без изменений ⇒ 0 событий.
- [x] **T013** [US4] Default sink registration: при импорте `apps/agent/daemon.py` регистрируется `SqliteTimelineSink(store_path=TimelineConfig.store_path)` если `TimelineConfig.enabled`. Flag-driven — off = полное отсутствие sink, zero overhead.
- [x] **T014** [US4] Integration-тест `tests/integration/timeline/test_hooks.py`: seven scenarios (US4.1–US4.4 + added/modified/removed отдельно). Использует `tmp_git_repo` фикстуру, реальные `git commit` + `git tag`.
- [x] **T015** **Checkpoint**: scan создаёт events без ручных вызовов на all-fixture репо ≥ 6 из 7 сценариев (SC-006). Latency overhead проверяется в Phase 8 T034.

---

## Phase 4: User Story 1 — «Что пропало после релиза Y» (Priority: P1, MVP)

**Goal**: `lvdcp_removed_since(ref)` возвращает ранжированный список удалённых символов.

**Independent Test**: `tests/integration/timeline/test_removed_since.py` — 3 тэга, известный набор удалений, Recall = Precision = 1.0, ответ ≤ 2 KB.

- [x] **T016** [US1] `libs/symbol_timeline/query.py::find_removed_since(store, project_root, ref, *, include_renamed=False, limit=50) -> RemovedSinceResult`. Ranking — по `importance` (из project_index) + recency (дата удаления), DESC.
- [x] **T017** [US1] `apps/mcp/tools.py::lvdcp_removed_since` + Pydantic response `RemovedSinceResponse{removed: list[RemovedSymbol], renamed: list[RenamePair], ref: str, ref_not_found: bool}`. Bounded output ≤ 20 KB через truncation + pagination (`cursor` field).
- [x] **T018** [P] [US1] Зарегистрировать tool в `apps/mcp/server.py::build_server`. Unit-тест `tests/unit/mcp/test_timeline_tools.py::test_removed_since_registration`.
- [x] **T019** [US1] Integration `tests/integration/timeline/test_removed_since.py` — US1 полный сценарий на `tmp_git_repo`.
- [x] **T020** **Checkpoint US1**: `lvdcp_removed_since` working end-to-end на synthetic repo; SC-001 будет измерен в Phase 8 T035 на реальной LV_DCP истории.

---

## Phase 5: User Story 2 — «Когда был реализован X» (Priority: P2)

**Goal**: `lvdcp_when(symbol)` — полная история одного символа.

**Independent Test**: `tests/integration/timeline/test_when.py` — символ с events `added → modified × 3 → renamed`, все возвращены в хронологическом порядке, ответ ≤ 3 KB.

- [x] **T021** [US2] `libs/symbol_timeline/query.py::symbol_timeline(store, project_root, symbol_id) -> SymbolTimelineResult`. Плюс `fuzzy_symbol_lookup(store, project_root, partial_name, limit=5)` — когда `symbol_id` не найден, возвращается топ-5 substring-матчей.
- [x] **T022** [US2] `apps/mcp/tools.py::lvdcp_when` + Pydantic `WhenResponse{events: list[TimelineEventDTO], symbol_id: str, candidates: list[SymbolCandidate], not_found: bool}`.
- [x] **T023** [P] [US2] Register в `server.py` + unit-тест регистрации.
- [x] **T024** [US2] Integration `tests/integration/timeline/test_when.py` — все 3 acceptance scenarios из spec US2.
- [x] **T025** **Checkpoint US2**: `lvdcp_when` зелёный; SC-002 latency (≤ 50 ms p95) проверяется в Phase 8 T034.

---

## Phase 6: User Story 3 — «Diff между релизами» + Release Hooks (Priority: P3)

**Goal**: `lvdcp_diff(from, to)`, `lvdcp_regressions(from, to)` + автоматические release snapshots. **Это Layer 3 hook — release watcher**.

**Independent Test**: `tests/integration/timeline/test_diff.py` + `test_release_snapshot.py`.

- [x] **T026** [US3] `libs/symbol_timeline/snapshot.py::build_snapshot(project_root, tag, head_sha) -> Snapshot`. Сохраняет copy of AST-row-ов + checksum в `symbol_timeline_snapshots`. SC-004: ≤ 500 ms для 5k символов.
- [x] **T027** [US3] `libs/gitintel/tag_watcher.py`: polling loop `poll_tags(root, known_tags_set) -> list[TagEvent]`, emit-ит `on_release(tag, head_sha, timestamp)` и `on_tag_invalidated(...)`. Интервал из `TimelineConfig.tag_watcher_poll_seconds`.
- [x] **T028** [US3] Wire tag_watcher в `apps/agent/daemon.py` — запускать в отдельном thread рядом с debounce loop; при новом тэге ⇒ `snapshot.build_snapshot`. Unit-тест с mock subprocess.
- [x] **T029** [P] [US3] `libs/symbol_timeline/query.py::diff(store, project_root, from_ref, to_ref) -> DiffResult{added, removed, modified, renamed}`. Использует snapshots (fast path) или реконструирует из events (fallback).
- [x] **T030** [US3] Два новых MCP-тулза: `apps/mcp/tools.py::lvdcp_diff` + `lvdcp_regressions` (regression = removed between releases) + Pydantic responses. Register в server.py.
- [x] **T031** [US3] Integration-тесты `tests/integration/timeline/test_diff.py` (US3 acceptance) + `test_release_snapshot.py` (tag_watcher → snapshot). Реальные `git tag` через `tmp_git_repo`.
- [x] **T032** **Checkpoint US3**: SC-005 `lvdcp_diff(v0.5.0, v0.6.1)` ≤ 200 ms / ≤ 15 KB на LV_DCP-монорепо (manual check); automatic checks на synthetic-репо зелёные.

---

## Phase 7: Reconcile + CLI + Git Hooks (Operations, US4 finish)

**Purpose**: Layer 2 (Claude Code git hooks) + reconcile + operator CLI. Завершает US4 и делает фичу production-ready.

- [x] **T033** `libs/symbol_timeline/reconcile.py::reconcile(store, project_root) -> ReconcileReport`. Находит events с `commit_sha` ∉ `git reflog`, помечает `orphaned=True`. **Никогда не удаляет.** Возвращает count per-event-type.
- [x] **T034** `apps/cli/commands/timeline.py`: `ctx timeline {enable, disable, status, reconcile, prune [--older-than], backfill [--since]}`. Status показывает last_scan_commit_sha, event count, orphaned count, DB size. Unit-тесты на каждую subcommand.
- [x] **T035** Claude Code hooks в `.claude/hooks/` — скрипты:
  - `post-commit.sh` — `ctx scan --incremental --commit-sha $(git rev-parse HEAD)`
  - `post-merge.sh` — то же + `ctx timeline reconcile` в фоне, если MERGE_HEAD existed
  - `post-checkout.sh` — **no-op на timeline** (только синкает `last_scan_commit_sha`)
  - `post-rewrite.sh` — `ctx timeline reconcile --orphaned`

  Плюс `docs/claude-hooks-setup.md` — инструкция по включению через `.claude/settings.json`.
- [x] **T036** Integration `tests/integration/timeline/test_reconcile.py` — `tmp_git_repo` с `git rebase`, events становятся orphaned, reconcile корректно их помечает; последующий `ctx timeline backfill` перехватывает.
- [x] **T037** **Checkpoint US4**: все 4 acceptance scenarios US4 (spec) зелёные end-to-end; Claude Code hooks exercised в `tests/integration/test_claude_hooks_smoke.py` (subprocess-уровень).

---

## Phase 8: Readiness, Observability, Rollout

**Purpose**: metrics (Layer 5), pack enrichment (Layer 4), feature flag gating, perf validation, staging.

- [x] **T038** Prometheus metrics в `libs/telemetry/timeline_metrics.py`: 5 метрик из plan.md Layer 5 (`symbol_timeline_events_total`, `_query_latency_seconds`, `_snapshot_build_seconds`, `_reconcile_orphaned_total`, `_sink_errors_total`). Инструментировать store + sinks + tools.
- [x] **T039** [P] structlog enrichment в `libs/scanning/scanner.py` + `apps/mcp/tools.py`: поля `event_type`, `symbol_id`, `commit_sha`, `duration_ms`. Unit-тест на presence полей через `structlog.testing.capture_logs`.
- [x] **T040** Pack enrichment (Layer 4) в `libs/context_pack/`: `detect_timeline_markers(query) -> bool` + `enrich_pack_with_timeline(pack, project_root, markers_hit)`. Гейт `TimelineConfig.enable_timeline_enrichment`. Добавляет секцию `## Timeline facts` ≤ 3 KB в итоговый pack. Integration-тест: query «когда был добавлен X» приводит к enriched pack-у.
- [x] **T041** `/readyz` check в `apps/backend/routes/` или `libs/mcp_ops/doctor.py`: timeline store reachable, последний scan не старше `now() - 7d` (или last_scan_commit_sha unset если проект только индексируется).
- [x] **T042** Perf-тест `tests/perf/test_scan_with_timeline.py` — SC-003: overhead scan с timeline vs без ≤ 10 %. Использует pytest-benchmark, baseline от `scan_project(timeline_enabled=False)`.
- [x] **T043** Rollout flag в `TimelineConfig.enabled`: по дефолту `True` в dev, `False` в prod compose до прохождения staging smoke-теста. Staging smoke-тест — manual runbook в `docs/runbooks/timeline-rollout.md`.
- [x] **T044** **Checkpoint Final**: все SC из spec зелёные на LV_DCP-монорепо; token footprint SC-001 измерен (manual `ctx pack` до/после с query «когда был реализован bge_m3»); fallback без timeline работает (set `enabled=False` → скан как раньше, zero events).

---

## Dependencies & Parallelism

**Critical path** (строго последовательные блоки):

```
Phase 1 (T001-T004)
  → Phase 2 (T005 → {T006, T007, T008 [P]} → T009 → T010)
    → Phase 3 (T011 → T012 → T013 → T014 → T015)
      ├→ Phase 4 US1 (T016 → T017 → T018 [P] → T019 → T020)
      ├→ Phase 5 US2 (T021 → T022 → T023 [P] → T024 → T025)
      └→ Phase 6 US3 (T026 → {T027, T028} → T029 [P] → T030 → T031 → T032)
        → Phase 7 (T033 → T034 → T035 → T036 → T037)
          → Phase 8 (T038 → {T039, T040, T041} → T042 → T043 → T044)
```

**Parallel lanes** (safe to run concurrently):
- **T002 + T003** (разные фикстуры)
- **T007 + T008** (differ и rename_detect не импортируют друг друга до Phase 3)
- **Phase 4 / Phase 5 / Phase 6** после Phase 3 — полностью независимые user stories
- **T018 + T023** (разные tool handlers, разные тесты регистрации)
- **T039 + T040 + T041** (observability / pack enrichment / readyz — разные модули)

## Story-to-phase matrix

| Story | Primary phase | Follow-up phase | Why |
|-------|---------------|-----------------|-----|
| US4 (hooks) | Phase 3 (scan) + Phase 7 (git hooks) | — | распадается на 2 hook-слоя по природе |
| US1 (removed_since) | Phase 4 | Phase 8 (pack enrichment, metrics) | нужен capture из Phase 3 |
| US2 (when) | Phase 5 | Phase 8 | тот же стор, независимый от US3 |
| US3 (diff + snapshots) | Phase 6 | Phase 7 (reconcile edge cases) | требует snapshots + tag_watcher |

## Out of Phase 2 MVP (optional polish)

- Obsidian sink (`libs/obsidian/timeline_sink.py`) — пример `sink_plugins` API.
- Dashboard endpoint (`apps/web/timeline.py`).
- `ctx timeline backfill --github-api` — обогащение PR/issue metadata.
- Cross-repo timeline.

---

**Total**: 44 tasks across 8 phases. Foundational + scan integration (T001–T015) — минимальный MVP-гейт для первого user-visible demo (`ctx timeline status` + events в store). US1 (T016–T020) — первая MCP-интеграция, которую имеет смысл показать пользователю.
