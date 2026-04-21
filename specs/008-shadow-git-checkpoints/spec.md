# Feature Specification: Shadow-git Checkpoints для Edit Pipeline (Phase 2)

**Feature Branch**: `008-shadow-git-checkpoints`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #8 — каждый шаг агентной правки коммитится в скрытый git-репо в `.context/shadow/`. Откат за одну команду. Пользовательский git не трогается. ТЗ §16 обязывает «edit guard pipeline».

## User Scenarios & Testing

### User Story 1 — Atomic undo агентной правки (Priority: P1)

Агент выполнил 5-шаговый рефакторинг. Пользователь видит, что шаг 3 испортил файл. Команда `ctx edit undo step-3` возвращает worktree в состояние после шага 2, пользовательский git history не затронут.

**Why this priority**: foundation Phase 2; без checkpoints агенту нельзя давать write-доступ.

**Independent Test**: `tests/integration/impact/test_shadow_git_undo.py` — 5 последовательных edit-steps → undo 3 → diff состояние файла соответствует concat(step1, step2).

**Acceptance Scenarios**:

1. **Given** агент выполнил 5 edit-steps, **When** `ctx edit undo step-3`, **Then** файлы возвращены к состоянию после step-2, в `.context/shadow/` создан новый commit "undo to step-2".
2. **Given** user sparallelly коммитил в основной репо во время edit, **When** undo в shadow, **Then** user commits НЕ затронуты (сами файлы вернулись, но user git log intact).

---

### User Story 2 — Полная история edit-сессии (Priority: P1)

`ctx edit history` показывает timeline: шаги, файлы, approx summary. Каждый шаг — shadow-git commit с metadata в commit message.

**Why this priority**: без истории нельзя аудировать агентные изменения.

**Independent Test**: run edit session → `ctx edit history` → ассертить формат output и количество commits.

**Acceptance Scenarios**:

1. **Given** 3-step edit session, **When** `ctx edit history`, **Then** output содержит 3+ entries (init + 3 steps), каждый с timestamp и metadata JSON.

---

### User Story 3 — Checkpoint перед рискованным шагом (Priority: P2)

Агент ставит эвристически "риск high" шагом (mass refactor) — автоматический checkpoint перед ним; плюс user может поставить `ctx edit checkpoint` вручную.

**Why this priority**: минимизирует blast-radius больших шагов.

**Independent Test**: rigged step с высоким risk-score → ассертить что shadow-commit создан ДО выполнения шага.

**Acceptance Scenarios**:

1. **Given** step с risk_score > 0.7, **When** pipeline готовится его выполнить, **Then** shadow-commit "checkpoint: pre-risk-step" создан первым.

---

### Edge Cases

- User git не инициализирован — shadow-git работает независимо (отдельный `git init` в `.context/shadow/`).
- Большие бинарные файлы — shadow-git их commit-ит; `.context/shadow/.gitignore` как fallback.
- Shadow репо растёт без границ — `ctx edit gc` периодически делает gc + squash старше 7 дней.
- Симлинки — shadow копирует реальное содержимое (не сами симлинки).
- Конфликт с user-совершённым commit'ом на те же файлы — undo применяется поверх user changes через git reflog apply.

## Requirements

### Functional Requirements

- **FR-001**: Модуль `libs/impact/shadow_git.py::ShadowGit(project_root: Path)`.
- **FR-002**: `ShadowGit.init_if_needed()` MUST создавать `.context/shadow/` как bare git-store, mirror файлов проекта (без user .git).
- **FR-003**: `ShadowGit.checkpoint(step: EditStep, files: list[Path], metadata: dict)` MUST создавать commit с файлом-ми в новом состоянии; commit message — JSON metadata (step_id, timestamp, risk_score, summary).
- **FR-004**: `ShadowGit.undo(to_checkpoint: str)` MUST восстанавливать файлы проекта в состояние checkpoint'а.
- **FR-005**: `ShadowGit.history(limit: int = 50)` MUST возвращать список HistoryEntry с metadata.
- **FR-006**: CLI команды `ctx edit checkpoint`, `ctx edit undo [step_id]`, `ctx edit history`, `ctx edit gc`.
- **FR-007**: Интеграция в `apps/agent/apply.py`: **ПЕРЕД** применением EditStep MUST вызываться `shadow.checkpoint()`; **ПОСЛЕ** — `shadow.after_apply(step)` для finalize.
- **FR-008**: Metadata commit'ов MUST включать `step.risk_score`, `step.summary`, `step.tool` (SEARCH/REPLACE vs patch).
- **FR-009**: `.context/shadow/` MUST быть в `.gitignore` пользовательского репо (добавляется автоматически через FR-002).
- **FR-010**: MUST работать на macOS / Linux; Windows out-of-scope.

### Key Entities

- **ShadowGit** — class, wraps `git` subprocess либо `pygit2`.
- **EditStep** — existing DTO; расширяется polями `risk_score`, `summary`.
- **HistoryEntry** — `{commit_sha, timestamp, step_id, metadata_json, files_changed}`.
- **Checkpoint** — alias для commit с special metadata tag.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Checkpoint для edit-шага с 10 файлами ≤ 100 МБ ≤ 500 мс.
- **SC-002**: Undo восстанавливает файлы за ≤ 1 с на 10 MB diff.
- **SC-003**: Zero случаев corruption user .git в eval-прогонах (100 runs).
- **SC-004**: Shadow repo gc работает: после 100 checkpoints gc уменьшает size ≥ 50%.
- **SC-005**: Integration-тесты на 3 конфигурациях (no user .git, dirty user .git, clean user .git) все зелёные.

## Assumptions

- `git` CLI доступен; либо `pygit2` wheel на macOS/Linux.
- Pip dep `pygit2` приемлем (binary wheels стабильно).
- ТЗ §16 — edit guard pipeline — прямое требование.
- Phase 2 — этот item работает после того, как item #9 (search/replace format) реализован.

## Dependencies & Constraints

- Зависит от: **#9 (search/replace edit format)** — edit pipeline должен генерировать EditStep DTO; plain patches тоже совместимы.
- Блокеров по другим items нет.
- Конституция: ТЗ §16 прямое требование; ADR-003 — агент owner edit-state, backend хранит только metadata.
- Privacy (#5): shadow-git хранит файлы как есть, но в `.context/shadow/` — локально, не уходит в Claude API; всё равно инспектится privacy layer при pack-формировании.
