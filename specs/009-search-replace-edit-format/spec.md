# Feature Specification: Search/Replace Edit Format вместо Unified Diff

**Feature Branch**: `009-search-replace-edit-format`
**Created**: 2026-04-21
**Status**: Draft
**Input**: ideas-bank item #9 — агент возвращает `SEARCH:`/`REPLACE:` блоки текста вместо patch-ей. LLM делает меньше ошибок, парсер — 50 строк, конфликт-detection — простой equality-check. Aider benchmarks показывают заметно выше pass-rate.

## User Scenarios & Testing

### User Story 1 — Надёжное применение LLM-правки (Priority: P1)

LLM генерирует edit для 500-строчного файла. Unified diff ломается: смещения строк плывут, контекст невалидный. SEARCH/REPLACE блок содержит exact text — либо найден (apply), либо нет (error с hint для retry).

**Why this priority**: robustness edit pipeline критичен для Phase 2; apply failures = потерянная работа агента.

**Independent Test**: бенчмарк `tests/eval/datasets/edit_tasks.yaml` — 50 edit-задач на реальных файлах. Apply success rate SEARCH/REPLACE vs udiff: +15 п.п.

**Acceptance Scenarios**:

1. **Given** файл с 500 строк и edit-block в формате SEARCH/REPLACE, **When** apply, **Then** файл точно обновлён, diff совпадает с ожиданием.
2. **Given** edit-block с SEARCH, который не найден (stale context), **When** apply, **Then** возвращается `StaleSearchError` с hint "re-read file and retry".

---

### User Story 2 — Множественные изменения в одном файле (Priority: P1)

Агент хочет сделать 3 независимых правки в одном файле. Каждая — отдельный SEARCH/REPLACE; применяются в порядке, с проверкой на неперекрывание.

**Why this priority**: реальные refactoring-задачи многоточечные.

**Independent Test**: тест с 3 блоками в одном файле; ассертит, что все 3 применены, diff соответствует ожиданию.

**Acceptance Scenarios**:

1. **Given** 3 non-overlapping SEARCH/REPLACE блока в file, **When** apply, **Then** все применены, результат совпадает с expected.
2. **Given** 2 overlapping блока (одна область), **When** apply, **Then** ошибка `OverlappingEditsError` с указанием.

---

### User Story 3 — Multi-file edit bundle (Priority: P2)

Агент возвращает edit-bundle (YAML или markdown с `<<<<<<< SEARCH file: path` headers); парсер раскладывает на отдельные файловые блоки.

**Why this priority**: Phase 2 edits обычно меняют 3-10 файлов; bundle — естественная единица.

**Independent Test**: bundle с edits для 3 файлов → apply → все применены атомарно (all-or-nothing через shadow-git #8).

**Acceptance Scenarios**:

1. **Given** bundle с блоками для 3 файлов, **When** apply, **Then** все 3 модифицированы; если один fail — shadow rollback (требует #8).

---

### Edge Cases

- SEARCH содержит уникальный текст в нескольких местах файла — ambiguous; `MultipleMatchesError`, требовать расширить контекст.
- Trailing whitespace / CRLF vs LF различия — normalize обе стороны перед matching.
- Empty SEARCH (insert at start) — специальный case: REPLACE инсёртится в начало файла.
- Empty REPLACE (delete) — удаление SEARCH блока.
- BOM в начале файла — сохраняется.
- File not found — `FileNotFoundError` с hint "create it first".
- Binary file — reject, SEARCH/REPLACE только для текста.

## Requirements

### Functional Requirements

- **FR-001**: Модуль `libs/impact/edit_format.py` экспортирует `parse_edit_bundle(text: str) -> EditBundle`, `apply_bundle(bundle: EditBundle, *, root: Path) -> ApplyResult`.
- **FR-002**: Format определён markdown-like:
  ```
  <<<<<<< SEARCH file: libs/foo.py
  def old():
      pass
  =======
  def new():
      return 42
  >>>>>>> REPLACE
  ```
- **FR-003**: Parser MUST быть ≤ 100 строк кода, без dependencies кроме stdlib.
- **FR-004**: Apply MUST быть idempotent при повторном запуске на уже применённом файле — return `AlreadyAppliedResult` без ошибки.
- **FR-005**: Conflict detection: перед apply пересчитать хэши SEARCH-блоков против current file; если mismatch → `StaleSearchError` с diff.
- **FR-006**: Whitespace normalization: `dedent` + trim trailing в SEARCH/REPLACE сравнении; **не** трогать содержимое файла вне матча.
- **FR-007**: CLI `ctx edit apply <bundle.md>` — читает stdin или file, применяет, отчёт в stdout.
- **FR-008**: Метрики: `edit_apply_total{result}` (success/fail/stale/conflict), `edit_block_count_histogram`, `edit_file_count_histogram`.
- **FR-009**: Интеграция с #8 (shadow-git): apply делает checkpoint перед, commit после.
- **FR-010**: Dry-run режим `--dry-run` печатает would-apply без изменений файлов.

### Key Entities

- **EditBundle** — `{edits: list[FileEdit]}`.
- **FileEdit** — `{path: Path, blocks: list[SearchReplaceBlock]}`.
- **SearchReplaceBlock** — `{search: str, replace: str, line_hint: int | None}`.
- **ApplyResult** — `{applied: list[str], skipped: list[str], errors: list[ApplyError]}`.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Apply success rate на `edit_tasks.yaml` (50 задач) **≥ 90%**, выше udiff baseline на **+15 п.п.**
- **SC-002**: Parser ≤ **100 LOC**, ≤ 10 ms на типовой bundle (10 блоков).
- **SC-003**: Apply 10-blocks bundle ≤ 500 мс (включая shadow-checkpoint).
- **SC-004**: Zero data loss в eval: на всех 50 задачах, если apply упал — файл не модифицирован (atomicity).
- **SC-005**: Human-readable error messages в 100% случаев ошибок apply (unit-тест на каждый ErrorKind).

## Assumptions

- LLM (Claude, и др.) могут надёжно генерировать SEARCH/REPLACE — подтверждается Aider-бенчмарками.
- Текстовые файлы UTF-8; non-UTF8 обрабатываются fall-through через `errors='replace'` с warning.
- User commits в тот же файл во время edit — rare race; обнаруживается через mtime/hash, обрабатывается через shadow-git (#8).
- Phase 2 scope — этот item foundational для всей edit pipeline; не блокируется Phase 1.

## Dependencies & Constraints

- Блокирует: #8 (shadow-git) — checkpoints нужны поверх этого формата; но #8 может работать и с другими форматами → skipping ordering не страшен.
- Независимо от: #1–7.
- Конституция ТЗ §16 — edit guard pipeline.
- ADR-003 — agent применяет, backend только хранит состояние.
- Privacy (#5): edit контент сканируется перед отправкой в LLM; результат (REPLACE-блок) от LLM сканируется при apply, если вставляет "новые секреты" из hallucinations.
