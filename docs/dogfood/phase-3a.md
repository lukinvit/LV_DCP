# Phase 3a Dogfood Report

**Date:** 2026-04-11
**Tag:** phase-3a-complete (pending)
**Author:** Vladimir Lukin

## Exit criterion: 7-step dogfood on 3 projects

Script: [scripts/phase-3a-dogfood.sh](../../scripts/phase-3a-dogfood.sh)

### Results

| Project | install | doctor | scan | launchd | handshake | uninstall | Manual edits |
|---|---|---|---|---|---|---|---|
| LV_DCP | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> |
| TG_Proxy_enaibler_bot | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> |
| TG_RUSCOFFEE_ADMIN_BOT | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> | <todo> |

## Changed surface

- New package `libs/mcp_ops/` (claude_cli, install, uninstall, doctor, launchd)
- Rewrote `apps/cli/commands/mcp_cmd.py` — new `install`, `uninstall`, `doctor` subcommands
- `apps/cli/commands/watch_cmd.py` — removed `--background`, added `install-service` / `uninstall-service`
- Daemon `last_scan_at_iso` update (`apps/agent/config.py`, `apps/agent/daemon.py`)
- `Graph.has_node` public API, dropped private `_fwd` / `_rev` access in `_walk_mixed`
- `Pipeline._stage_graph` refactor: non-optional `Graph` argument
- `.env.*` prefix-based ignore with `.env.example` allow-list
- `ScanResult.relations_extracted` → `relations_reparsed` + new `relations_cached`
- Runtime-built secret test patterns (test file no longer self-flags)
- 16 backlog items landed — see commit range `phase-2-complete..phase-3a-complete`

## Cost / latency on canary repo (LV_DCP)

Measured values to be filled in during Task 20 final gate:

| Metric | Phase 2 close | Phase 3a close | Delta |
|---|---|---|---|
| cold scan | 0.52s | <todo> | <todo> |
| warm scan | 0.28s | <todo> | <todo> |
| ctx mcp doctor (all 7 checks) | — | <todo> | new |
| files / symbols / relations_cached | 156 / 1063 / 2439 | <todo> | <todo> |

## Eval metrics (must not regress)

| Metric | Threshold | Phase 2 close | Phase 3a close |
|---|---|---|---|
| recall@5 files | ≥ 0.85 | 0.891 | <todo> |
| precision@3 files | ≥ 0.60 | 0.620 | <todo> |
| recall@5 symbols | ≥ 0.80 | 0.833 | <todo> |
| impact_recall@5 | ≥ 0.75 | 0.819 | <todo> |

## Known issues

- To be filled during final gate.

## Next up: Phase 3b

See [docs/superpowers/specs/2026-04-11-phase-3a-design.md § 11](../superpowers/specs/2026-04-11-phase-3a-design.md#11-dependencies-на-phase-3b3c).
