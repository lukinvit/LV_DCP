# ADR-003: Single-writer model — agent owns file state, backend owns retrieval state

**Status:** Accepted
**Date:** 2026-04-10
**Supersedes:** —

## Context

ТЗ разделяет ответственности между desktop agent и backend, но не фиксирует протокол синхронизации. На практике оба компонента обладают **частично пересекающейся информацией** о проектах:

- Агент знает: что файлы существуют, их mtime/hash, какие изменились, какие удалены
- Backend знает: какие summaries построены, какие embeddings индексированы, какие relations выведены, какие packs собраны

Классическая two-writer проблема: если оба компонента пишут в пересекающиеся поля, рано или поздно возникает расхождение, которое невозможно разрешить без ad-hoc эвристик. Примеры реальных багов, которых надо избежать:

- Удалил проект локально → через час вернулся потому что backend его не знал удалённым
- Agent скачал commit, backend ещё не переиндексировал → retrieval возвращает устаревшие символы
- Оба компонента одновременно пишут в одну таблицу и последний выигрывает

Конституция Раздел II.6 объявляет single-writer инвариантом. Этот ADR фиксирует контракт.

## Decision

### 1. Разделение владения

| Сущность | Owner | Writer | Readers |
|---|---|---|---|
| File existence, path, hash, mtime, size, language | **agent** | agent | agent, backend |
| Delete tombstones | **agent** | agent | backend |
| Project registry (workspace, path, tags, policies) | **backend** | backend (via `ctx project add`) | agent, backend |
| Scan job state (queued/running/done/failed) | **backend** | backend | agent (read-only via API) |
| Parse results (symbols, relations) | **backend** | backend worker | — |
| Summaries, embeddings, retrieval traces | **backend** | backend worker | — |
| Context packs, edit packs | **backend** | backend | — |
| Local SQLite cache of file state | **agent** | agent | agent |

**Правило:** у каждого поля данных ровно один владелец. Читать может кто угодно. Писать — только owner.

### 2. Протокол обмена

Только **однонаправленный push от агента к backend** + ACK:

```
agent scans local FS
  → computes FileDelta (added / modified / deleted / unchanged)
  → POST /projects/{id}/ingest { delta_batch }
      body: [
        { path, content_hash, size, mtime, language, action },
        ...
      ]
  → backend persists FileState rows in its own DB
  → backend enqueues scan jobs for added/modified files
  → backend responds { accepted: [...], rejected: [...], batch_id }
  → agent commits delta to local SQLite ONLY after ACK
```

Агент **не** делает прямых запросов в Postgres или Qdrant. Всё через HTTP API.
Backend **не** читает локальную файловую систему напрямую. Для чтения содержимого — запрашивает у агента через отдельный endpoint или агент сам отправляет содержимое в ingest батче (для файлов в пределах size limit).

### 3. Политика разрешения конфликтов

Если backend уже знает файл с hash `A`, а агент отправляет тот же путь с hash `B`:
- **Agent wins.** Backend перечитывает, перепарсивает, пересчитывает всё производное.
- Backend **никогда** не «исправляет» agent. Если backend сомневается в данных agent'а — это баг agent'а, не backend'а.

Если агент не видит файл, который backend помнит:
- Агент присылает `delete` tombstone → backend удаляет производные (symbols, relations, summaries — через cascade), помечает File как `is_deleted=true`
- Soft delete, не hard delete — для истории и возможного undo

### 4. Идемпотентность

- `ingest` эндпоинт идемпотентен по `batch_id` (UUID, генерируется агентом)
- Повторный ingest того же batch_id → backend возвращает тот же ACK без повторной работы
- Агент может повторять отправку до первого успешного ACK; не должен дублировать локальные коммиты

### 5. Разделение scan state

- Postgres таблица `scan_jobs` — только backend пишет
- Агент читает `GET /projects/{id}/scans` для отчётов `ctx doctor` и статусных индикаторов
- Если агенту нужно «отменить scan», он отправляет `POST /scans/{id}/cancel` — это read-write операция **на своей стороне** через API, не прямой DB write

### 6. Agent local cache (SQLite) schema

Агент хранит в SQLite только **своё** представление:

```sql
CREATE TABLE file_state (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    language TEXT,
    last_synced_batch_id TEXT,    -- NULL если ещё не отправлено в backend
    last_synced_at REAL
);

CREATE TABLE pending_deltas (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    action TEXT NOT NULL,          -- added | modified | deleted
    detected_at REAL NOT NULL,
    batch_id TEXT
);
```

Агент не дублирует backend'овские таблицы (symbols, summaries, embeddings). Если агенту нужна эта информация — он запрашивает backend.

### 7. Fail-safe режим

Если backend недоступен:
- Агент продолжает собирать deltas в `pending_deltas`
- Дожимает при восстановлении связи
- CLI запросы (`ctx ask`, `ctx pack`) — возвращают явную ошибку «backend offline, last known state at T», **не** пытаются ответить по stale локальным данным

Если агент недоступен:
- Backend продолжает обслуживать retrieval по последнему известному состоянию
- `ctx doctor` у backend показывает `agent: disconnected since T`
- Incremental scan останавливается; нет новых deltas — нет новых данных

## Consequences

### Positive
- Zero ambiguity: для каждого поля данных — один writer. Debuggable.
- Простая sync-модель: один направленный поток + ACK.
- Fail-safe режимы явные и тестируемые.
- Агент можно перезапускать, убивать, удалять SQLite кеш — backend не портится.

### Negative
- Backend не может сам инициировать scan (например «пересмотри этот файл»). Он может попросить агента через long-poll или push, но это усложнение, вынесенное за MVP.
- При больших initial scan'ах payload ingest может быть объёмным — нужна пагинация (`batch_size ≤ 500 файлов` на один HTTP-вызов).
- Архитектура сложнее, чем «пусть backend сам ходит по FS». Это сознательный trade-off ради robust-ности.

### Operational
- Health check `GET /health/dependencies` backend'а включает `agent_last_seen_at` для каждого подключённого агента.
- Metrics: `agent_ingest_lag_seconds`, `pending_deltas_count`, `ingest_batch_size_bytes`.
- Backup strategy: Postgres backup + Qdrant snapshot покрывают backend state; SQLite cache агента — одноразовый, при потере пересчитывается из FS.

## Alternatives considered

1. **Backend reads FS directly** — отвергнуто. Требует shared filesystem или SSH; плохо работает с FSEvents; ломает границу local/remote.
2. **Bidirectional sync with CRDTs** — отвергнуто как несоразмерная сложность для single-user системы.
3. **Agent embeds minimal retrieval engine, backend optional** — рассмотрено, но отложено. В Phase 1 (pure CLI) это де-факто так и будет — агент отсутствует, CLI работает локально. Backend добавляется в Phase 3, и тогда single-writer модель вступает в силу.
4. **Event sourcing** (агент пишет event log, backend применяет) — оставлено как потенциальное улучшение Phase 5+ для audit trail.
