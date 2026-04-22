# Research: Symbol Timeline Index (Phase 0)

**Date**: 2026-04-22
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Три открытых вопроса до implementation-а. Каждый решён c trade-off-ами — фиксируем, чтобы не переоткрывать.

## R1 — Rename detection: `git --follow` vs content-hash similarity

### Context
FR-002 требует, чтобы при `git mv a.py b.py` или `git log --follow` показывал переименование, таймлайн эмитил `renamed` вместо пары `removed + added`. Spec-порог confidence ≥ 0.85.

### Options

| Подход | Плюсы | Минусы |
|--------|-------|--------|
| `git log --follow <path>` subprocess | Точность близка к 1.0 на файловом уровне; использует встроенный rename detector git | Работает только для файлов; **не** различает rename отдельного символа при `git mv`, который тронул несколько функций. Медленный при крупных batch-ах (один subprocess на файл). |
| SimHash / MinHash по токенам | Быстрый; символ-уровневый; не зависит от git-state | Требует держать токен-снэпшот в памяти; false positives на близких функциях; порог нужно тюнить |
| Qualified-name last-segment match | Stdlib only (`difflib.SequenceMatcher`); дешёвый | Ломается при настоящем переименовании символа (`parse_user` → `parse_account`) |
| Content-hash exact match | Бесплатный — уже есть в differ | Differ ловит это как `moved`; для renames бесполезен |

### Decision

**Hybrid, по слоям**:

1. **Differ** решает: равный `content_hash` при разных `file_path` → сразу `moved` event. Rename detect это даже не видит.
2. **Rename detect** (MVP, Phase 2): pairing по `qualified_name` last-segment + `SequenceMatcher.ratio()` для fallback. Порог `0.85`. Tune-able через `TimelineConfig.rename_similarity_threshold`.
3. **Rename detect** (Phase 7 enhancement): подключить `git log --follow` как дополнительный сигнал для файл-уровневых переименований. Symbol-level продолжает использовать ratio; при несогласии git vs ratio — `is_candidate=True` флаг, решение откладывается на human review через `ctx timeline review-renames`.

### Rationale
Phase 2 получает тестируемый API без внешних зависимостей (subprocess). Phase 7 добавляет точность через git без переписывания контракта. `SequenceMatcher` — stdlib, консервативный (недо-матчит скорее, чем пере-матчит), пользователь ничего не теряет — непарные пары остаются как `removed + added`.

---

## R2 — AST-snapshot storage: blob в `.context/cache.db` vs отдельные msgpack-файлы

### Context
Differ-у нужен snapshot предыдущего скана. Текущий `ProjectIndex` хранит per-symbol records в SQLite, но не immutable снэпшот на момент последнего скана.

### Options

| Подход | Плюсы | Минусы |
|--------|-------|--------|
| BLOB-колонка в существующей `.context/cache.db` | Атомарность со скан-транзакцией; один backup | Раздувает SQLite; page-level locks при чтении snapshot и write scan могут сериализоваться |
| Отдельный файл `.context/snapshots/<commit_sha>.msgpack` | Изолированы от scan write-path; легко GC-ить; возможность хранить множество исторических snapshots | Нужен GC-скрипт; не атомарен со scan commit |
| Derive-on-demand: выбрать все `project_index.symbols` WHERE last_scan_commit_sha=? | Не требует миграции | Медленно на каждом скане; старые symbols уже удалены к моменту следующего скана |

### Decision

**Файлы**. Добавляем директорию `.context/snapshots/` с файлами вида `<snapshot_key>.msgpack.zst`.

- `snapshot_key` — `sha256(project_root | last_scan_commit_sha | scan_id)[:16]`. Если `commit_sha=None` (dirty working tree), используется `scan_id` UUIDv7.
- Формат — `msgpack` + `zstandard` (level 3) compression.
- GC — retention: последние 5 snapshots + все, на которые ссылается release snapshot. Sweep запускается в `ctx timeline prune`.
- Size estimate: ~5k символов × (symbol_id 64B + file_path 60B + content_hash 64B + qualified_name 80B) ≈ 1.3 MB pre-compress → ~300 KB post-compress. 5 snapshots ≈ 1.5 MB.

### Rationale
Изоляция от scan write-path критичнее, чем атомарность — scan rerun безопасен даже если предыдущий snapshot не флашнулся. Разделение ответственностей — cache.db хранит «что знаем сейчас», snapshots хранят «что знали на каком commit». GC простой (mtime-based + anchor-list).

### Fallback
Если msgpack/zstd зависимости отвергнуты (минимальные external deps) — переключиться на JSON + gzip stdlib. ~10% больше на диске, той же простоты.

---

## R3 — Release boundary detection: polling vs FSEvents vs git hooks

### Context
Release snapshot (FR-005) должен триггериться на `git tag`. Нужна надёжная доставка без root-прав и с минимальной latency.

### Options

| Подход | Latency | Надёжность | Требования |
|--------|---------|------------|------------|
| Polling `git for-each-ref` каждые 60 с | ~60 s | High (без propagation gaps) | Только git в PATH |
| FSEvents/watchfiles на `.git/refs/tags/` | ~10 ms | Medium (race conditions при packed-refs) | `watchfiles` (spec #4) |
| Native `.git/hooks/post-update` или `post-receive` | <1 s | High, но требует модификации репо | User modifies `.git/hooks/` — invasive |
| Claude Code hook `post-tag.sh` | ~100 ms | High, в пользовательском управлении | Включается через `.claude/settings.json` |

### Decision

**Polling как default (60 s); opt-in Claude Code hook для low-latency пользователей**.

- `libs/gitintel/tag_watcher.py` — polling loop: `git for-each-ref --sort=-taggerdate refs/tags --format='%(refname:short) %(objectname) %(taggerdate:iso)'`.
- Interval из `TimelineConfig.tag_watcher_poll_seconds = 60`.
- При обнаружении нового тэга → `on_release` hook → snapshot builder.
- Packed-refs handled: `git for-each-ref` покрывает оба storage-а (loose + packed).
- Opt-in Claude Code hook `.claude/hooks/post-tag.sh` — вызывает `ctx timeline snapshot --tag <name>` напрямую, минуя polling lag.
- Если `watchfiles` (spec #4) лендится — добавить adapter-path, который подписывается на `.git/refs/tags/`.

### Rationale
Polling покрывает 95 % кейсов без новых зависимостей. 60 с лаг приемлем — release snapshot фиксирует «момент обнаружения», а не `git tag`. Claude Code hook даёт low-latency для тех, кому важно. FSEvents-путь готов к активации, но не MVP.

### Edge: tag с тем же именем пересоздан
Polling фиксирует изменение `objectname` при том же `refname:short` → `on_tag_invalidated(old_head_sha, new_head_sha)`. Старый snapshot помечается `tag_invalidated=True`, **не** удаляется.

---

## Summary of decisions

| ID | Вопрос | Решение |
|----|--------|---------|
| R1 | Rename detection | Hybrid: differ→moved + MVP last-segment ratio, Phase 7 enrich with `git --follow` |
| R2 | AST snapshot storage | `.context/snapshots/<key>.msgpack.zst` с GC retention=5 + anchor-list |
| R3 | Tag detection | Polling 60 s default + opt-in Claude Code `post-tag.sh` hook |

Все три решения обратно-совместимы с будущими улучшениями (SimHash, FSEvents, shadow-checkpoints) без контрактных изменений.
