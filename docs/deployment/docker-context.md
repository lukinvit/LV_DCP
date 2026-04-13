# Docker context: `docker-vm`

LV_DCP serverside (Postgres, Qdrant, Redis/Dragonfly, backend, worker) **всегда** запускается через удалённый Docker context `docker-vm`. Локальный `desktop-linux` context используется только для одноразовых экспериментов и не принимается в production пайплайн.

## Зачем удалённый context

1. **Разделение машин.** macOS рабочая станция не должна держать Postgres/Qdrant под нагрузкой — батарея, шум вентиляторов, конфликт портов с IDE.
2. **Стабильная топология.** VM доступна по стабильному доменному имени, не зависит от того, включен ли Mac.
3. **Ближе к прод-реализму.** Тестирование backend'а на Linux-хосте даёт те же гарантии, что и продакшен позднее.
4. **Безопасность сети.** Postgres/Qdrant/Redis не слушают на localhost Mac'а, где любой локальный процесс мог бы обратиться без auth.

## Контекст

```bash
docker context ls
# NAME             DESCRIPTION                               DOCKER ENDPOINT
# default          Current DOCKER_HOST based configuration   unix:///var/run/docker.sock
# desktop-linux    Docker Desktop                            unix://~/.docker/run/docker.sock
# docker-vm *                                                ssh://user@docker.your-host.example:2222
# home                                                       ssh://docker-vm
```

Звёздочка рядом с `docker-vm` означает, что это активный контекст.

## Правила

### Активация для сессии

Два способа, оба допустимы:

```bash
# Способ 1: через env для одной команды
DOCKER_CONTEXT=docker-vm docker compose -f deploy/docker-compose/dev.yml up -d

# Способ 2: через Makefile (рекомендуется)
make docker-up     # использует DOCKER_CTX=docker-vm по умолчанию
make docker-logs
make docker-down
```

### Что запускается на `docker-vm`

- `postgres:16` — primary DB
- `qdrant/qdrant` — vector store (**фаза 5+**, в фазах 1–2 не нужен)
- `dragonflydb/dragonfly` или `redis:7-alpine` — queue/cache
- `backend` — FastAPI (когда появится, **фаза 3+**)
- `worker` — Dramatiq/RQ (когда появится, **фаза 3+**)

### Что НЕ запускается на `docker-vm`

- **Desktop agent** — нативный Python процесс на локальном Mac через `launchd`, не Docker
- **CLI (`ctx`)** — локальный Python процесс на Mac
- **Eval harness** — локально, потому что fixture repo на диске разработчика
- **pytest, ruff, mypy** — локально

### Сетевые правила

- Compose-файл **не** пробрасывает порты Postgres/Qdrant/Redis на `0.0.0.0` VM
- Backend публикует только `8080` для API
- Доступ к внутренним сервисам — только через `docker exec` или отдельный debug-override compose файл
- `.env` с credentials лежит **на VM**, не в git; копируется вручную один раз, ротируется при инциденте

### Volumes

Именованные Docker volumes на VM:
- `dcp_pgdata` — Postgres data
- `dcp_qdrantdata` — Qdrant storage (когда появится)
- `dcp_redisdata` — Redis/Dragonfly persistence

Volumes **не** монтируются из git-репо. Бэкапы делаются через Postgres `pg_dump` и Qdrant snapshots (см. процедуру в `docs/deployment/backup.md` — будет создан в Phase 3).

## Проверка health из Mac

```bash
# список запущенных контейнеров на VM
DOCKER_CONTEXT=docker-vm docker ps

# логи конкретного сервиса
DOCKER_CONTEXT=docker-vm docker compose -f deploy/docker-compose/dev.yml logs -f postgres

# заход в контейнер
DOCKER_CONTEXT=docker-vm docker compose -f deploy/docker-compose/dev.yml exec postgres psql -U dcp
```

## Что делать, если нужен локальный Docker

В редких случаях (эксперимент, отладка compose-файла) можно временно переключиться на `desktop-linux`:

```bash
DOCKER_CONTEXT=desktop-linux docker compose -f deploy/docker-compose/dev.yml up -d
```

**Но:**
- Это не production путь
- Credentials из `.env` на VM использовать нельзя (должны быть отдельные local-only)
- После эксперимента — `docker compose down -v` для очистки

## Phase gating

| Phase | Что на docker-vm |
|---|---|
| 0 | Ничего (нет server кода) |
| 1 | Ничего (local CLI only) |
| 2 | Ничего (ещё local CLI + sqlite-vss) |
| 3 | Postgres, Redis/Dragonfly, backend, worker |
| 5 | + Qdrant (если метрики требуют) |
