# LV_DCP — Developer Context Platform

Локально-удалённая инженерная память: превращает локальные проекты на macOS в управляемый слой контекста для Claude, IDE и человека.

**Статус:** pre-phase-0 (инициализация).

## Документы, которые обязаны быть прочитаны перед любым изменением

1. [CLAUDE.md](CLAUDE.md) — стек, конвенции, правила зависимостей
2. [docs/constitution.md](docs/constitution.md) — неизменяемые принципы проекта
3. [docs/tz.md](docs/tz.md) — исходное ТЗ (1842 строки)
4. [docs/adr/](docs/adr/) — Architecture Decision Records
5. [docs/superpowers/plans/](docs/superpowers/plans/) — действующий план фазы

## Быстрый старт для разработки

```bash
# (когда pyproject будет наполнен зависимостями)
make install
make lint typecheck test
```

Серверная инфраструктура (Postgres, Qdrant, Redis, backend, worker) **всегда** запускается через удалённый docker context `docker-vm`. См. [docs/deployment/docker-context.md](docs/deployment/docker-context.md).
