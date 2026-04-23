# Plan — spec-011 Project Copilot Wrapper

## Architecture

```
ctx project check   ─┐
ctx project refresh ─┤
ctx project wiki    ─┼─► apps/cli/commands/project_cmd.py  (thin Typer)
ctx project ask     ─┘              │
                                    ▼
                     libs/copilot/orchestrator.py  (pure library)
                                    │
           ┌────────────────────────┼────────────────────────┐
           ▼                        ▼                        ▼
    libs/scanning               libs/wiki                libs/status
    libs/context_pack           apps/mcp/tools.lvdcp_pack (for ask)
```

All side effects happen through the existing primitives — no new DB,
queue, or on-disk artifact. The copilot is a composition layer.

## Module layout

- `libs/copilot/models.py`
  - `DegradedMode(Enum)` — `not_scanned | stale_scan | wiki_missing | wiki_stale | qdrant_off | ambiguous`.
  - `CopilotCheckReport` — scan state, wiki state, retrieval capability.
  - `CopilotRefreshReport` — what was refreshed, what was skipped.
  - `CopilotAskReport` — pack markdown + coverage + degraded modes.
- `libs/copilot/orchestrator.py`
  - `check_project(root, *, config_path) -> CopilotCheckReport`
  - `refresh_project(root, *, full, refresh_wiki) -> CopilotRefreshReport`
  - `refresh_wiki(root, *, all_modules) -> CopilotRefreshReport`
  - `ask_project(root, query, *, mode, limit, auto_refresh=False) -> CopilotAskReport`
- `libs/copilot/__init__.py` — re-export public functions and models.

## CLI surface

```
ctx project check   <path>           # prints CopilotCheckReport
ctx project refresh <path> [--full] [--no-wiki]
ctx project wiki    <path> [--refresh] [--all]
ctx project ask     <path> <query> [--mode navigate|edit] [--limit 10] [--refresh]
```

All commands share a `--json` flag that emits the pydantic DTO as
indented JSON. Humans default to the text rendering.

## Degraded-mode matrix

| Condition                         | Detection                                        | Message                               |
|-----------------------------------|--------------------------------------------------|---------------------------------------|
| `.context/cache.db` missing       | `ProjectIndex.open(root)` raises `ProjectNotIndexedError` | "not scanned — run `ctx project refresh`" |
| `HealthCard.stale=True`           | `last_scan_at_iso` older than 24 h               | "index > 24 h stale"                  |
| `.context/wiki/INDEX.md` missing  | file check                                       | "no wiki yet — run `ctx project wiki --refresh`" |
| wiki has dirty modules            | `get_dirty_modules(conn)` non-empty              | "N module(s) need wiki refresh"       |
| `cfg.qdrant.enabled=False`        | `load_config(...).qdrant.enabled`                | "vector search off — keyword fallback"|
| pack coverage == "ambiguous"      | `PackResult.coverage`                            | "ambiguous — consider `ctx explain`"  |

Each condition maps 1-to-1 to a `DegradedMode` enum value; the report
carries a list of active modes, so consumers (JSON, text, future UI)
render them the same way.

## Tests

- `tests/unit/copilot/test_check_project.py` — tmp_path fixtures for
  scanned / not-scanned / stale projects.
- `tests/unit/copilot/test_refresh_project.py` — scan + wiki
  orchestration, with `--no-wiki` short-circuit.
- `tests/unit/copilot/test_ask_project.py` — happy path, `not_indexed`
  auto-refresh path, ambiguous coverage surfacing.
- `tests/unit/cli/test_project_cmd.py` — `CliRunner` invocations of each
  subcommand, assert exit codes and key text snippets.

Total target: ~15–20 new tests, all under the fast marker. No new Qdrant
dep; we mock the vector-search path.
