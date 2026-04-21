# Edit safety: pipeline безопасных правок

6 идей для фазы 2. Без этого слоя давать агенту write-доступ нельзя.

Все идеи ТЗ §16 (обязательный цикл edit-задачи: intent → edit scope → build edit pack → impact analysis → plan → patch → lint/typecheck/test → change summary) и ADR-003 (single-writer).

---

## 1. Shadow-git checkpoints

- **Что даёт:** каждый шаг агентной правки автоматически коммитится в скрытый git-репо `.context/shadow/`. Пользовательский `.git` не трогается. Откат за одну команду, визуализация цепочки шагов.
- **Проблема:** без checkpoints автоматические правки — русская рулетка. Одна ошибка LLM = потеря часа работы.
- **Где:** `libs/impact/shadow_git.py`, `apps/agent/apply.py`.
- **Влияние:** **H** — обязательный foundation фазы 2.
- **Срок:** **1 неделя** (FS-hooks нетривиальны, особенно обработка renames).
- **Источник:** Cline workspace-checkpoints, Cursor shadow workspace.

---

## 2. Search/replace edit format вместо unified diff

- **Что даёт:** агент возвращает `SEARCH: <старый текст>\nREPLACE: <новый текст>` блоки. Парсер — 50 строк, конфликт-detection — простой equality-check на older text. Заметно меньше ошибок LLM vs udiff.
- **Проблема:** unified diff сложно сгенерировать и легко сломать (смещения строк плывут, \ No newline, контекстные строки). Aider бенчмарки показывают stable **~5–15% разрыв pass-rate** в пользу search/replace.
- **Где:** `libs/impact/edit_format.py`.
- **Влияние:** **H**.
- **Срок:** **1–2 дня**.
- **Источник:** Aider.

---

## 3. LangGraph-style state machine для edit pipeline

- **Что даёт:** цикл ТЗ §16 формализуется как StateGraph: `intent → scope → pack → impact → plan → patch → validate → summary`. Условные переходы, retry/resume, явные checkpoints, наблюдаемость.
- **Проблема:** edit-cycle сейчас — процедурный код с ad-hoc early returns. Добавить retry или resume после failure без рефакторинга невозможно.
- **Где:** `libs/impact/edit_graph.py`, `apps/cli/edit.py`. Реализуем свой async StateGraph без зависимости от LangGraph.
- **Влияние:** **H** для maintainability.
- **Срок:** **3–5 дней**.
- **Источник:** LangGraph, Letta.

---

## 4. Apply-model: дешёвая быстрая модель для применения diff

- **Что даёт:** большая модель (Opus/Sonnet) пишет *намерение* правки в человеческом языке, апply-модель (Haiku) преобразует в конкретный diff. Разделение ролей — прямая экономия $$$ на длинных outputs.
- **Проблема:** Opus тратит половину токенов на аккуратное форматирование diff'ов — это boilerplate-работа, не инженерная.
- **Где:** `libs/impact/apply_model.py`.
- **Влияние:** **M-H** (экономия cost, ускорение).
- **Срок:** **1 день** обвязки.
- **Источник:** Cursor «apply model».

---

## 5. Shadow-workspace / overlay FS

- **Что даёт:** патчи применяются в overlay-директории, коммитятся в реальный FS **только после** зелёных тестов. На macOS — через APFS `clonefile` + overlay dir.
- **Проблема:** закрывает последнюю дыру edit safety: даже с shadow-git между apply и test есть окно, когда реальный FS содержит сломанный код.
- **Где:** `libs/impact/overlay_fs.py`, `apps/agent/overlay.py`.
- **Влияние:** **H** для фазы 2-финала.
- **Срок:** **1–2 недели** (нетривиально, особенно cross-tool invalidation).
- **Источник:** Cursor «shadow workspace», OpenHands runtime.

---

## 6. Memory operations enum (ADD/UPDATE/DELETE/NOOP)

- **Что даёт:** когда пользователь говорит «переименуй X в Y» или «добавь правило: используем Pydantic v2», агент решает через enum что делать с существующими записями в patterns/preferences/memory. Не append-only, а семантический update.
- **Проблема:** текущая память накапливает противоречащие факты. Никакого дедупа, никакого обновления.
- **Где:** `libs/memory/ops.py`, `libs/memory/extractor.py`.
- **Влияние:** **M**.
- **Срок:** **3–5 дней**.
- **Источник:** mem0.

---

## Порядок внедрения

```
┌──────────────────────────────────────────────────┐
│ 1. Search/replace edit format        (1–2 дня)   │
│ 2. Shadow-git checkpoints            (1 неделя)  │  ← достаточно для safe "suggest + approve"
│ 3. LangGraph state machine           (3–5 дней)  │
│ 4. Apply-model routing               (1 день)    │
│ 5. Memory ops                        (3–5 дней)  │
│ 6. Shadow-workspace overlay FS       (1–2 нед)   │  ← обязательно для autonomous apply
└──────────────────────────────────────────────────┘
```

После шага 2 уже можно давать агенту write-доступ в режиме «suggest + user approve». После шага 6 — можно экспериментировать с auto-apply на CI-покрытых проектах.

## Связанные ADR

- **ADR-003 Single-writer model** — agent владеет FS, backend владеет DB. Shadow-git и overlay-FS не нарушают это: оба работают внутри agent-домена.
- **Новый ADR-004 (предложение):** Edit safety contract — shadow-git обязателен, overlay-FS обязателен для auto-apply, search/replace — рекомендуемый формат.
