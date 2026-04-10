# Architecture Decision Records

Каждый ADR — нумерованный, датированный, иммутабельный. Если решение меняется, создаётся **новый** ADR с пометкой `Supersedes: ADR-NNN`, а старый помечается `Status: Superseded by ADR-MMM`.

## Статусы

- **Proposed** — черновик, ещё не принят
- **Accepted** — принят, является действующим контрактом
- **Superseded** — заменён новым ADR
- **Deprecated** — больше не актуален, но не заменён (редкий случай)

## Текущие ADR

| # | Title | Status | Date |
|---|---|---|---|
| [001](001-budgets.md) | Cost, latency and resource budgets | Accepted | 2026-04-10 |
| [002](002-eval-harness.md) | Retrieval evaluation harness as contract | Accepted | 2026-04-10 |
| [003](003-single-writer-model.md) | Single-writer model: agent owns file state, backend owns retrieval state | Accepted | 2026-04-10 |

## Формат

Каждый ADR содержит:

- **Context** — что и зачем решаем
- **Decision** — что именно решили (конкретно)
- **Consequences** — последствия, включая негативные
- **Alternatives considered** — какие варианты отвергли и почему
