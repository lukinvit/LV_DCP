# Phase 3a Dogfood Report

**Date:** 2026-04-11
**Tag:** phase-3a-complete
**Author:** Vladimir Lukin

## Exit criterion: 7-step dogfood on 3 projects

Script: [scripts/phase-3a-dogfood.sh](../../scripts/phase-3a-dogfood.sh)
Full log: `/tmp/phase-3a-dogfood.log`

### Results

| Project | install | doctor | scan | launchd | handshake | uninstall | Manual edits |
|---|---|---|---|---|---|---|---|
| LV_DCP | ✓ | ✓ 7/7 | 176 files / 0.32s warm | ✓ bootstrap+bootout | ✓ | ✓ | none |
| Project_Medium_A | ✓ | ✓ 7/7 | 146 files / 0.56s warm | ✓ bootstrap+bootout | ✓ | ✓ | none |
| Project_Medium_B | ✓ | ✓ 7/7 | 109 files / 0.30s warm | ✓ bootstrap+bootout | ✓ | ✓ | none |

**Dogfood exit code: 0 (zero failures across all 3 projects × 7 steps).**

## Changed surface

- New package `libs/mcp_ops/` (`claude_cli`, `install`, `uninstall`, `doctor`, `launchd`)
- Rewrote `apps/cli/commands/mcp_cmd.py` — new `install`, `uninstall --legacy-clean`, `doctor --json` subcommands
- `apps/cli/commands/watch_cmd.py` — removed `--background`, added `install-service` / `uninstall-service`
- Daemon `last_scan_at_iso` update hook (`apps/agent/config.py`, `apps/agent/daemon.py`)
- `Graph.has_node` public API, dropped private `_fwd` / `_rev` access in `_walk_mixed`
- `Pipeline._stage_graph` refactor: non-optional `Graph` argument (no more bare assert)
- `.env.*` prefix-based ignore with `.env.example` allow-list
- `ScanResult.relations_extracted` → `relations_reparsed` + new `relations_cached`
- Runtime-built secret test patterns (test file no longer self-flags)
- `libs/core/version.py` single source of truth for `LVDCP_VERSION`
- ADR-001 stale LLM/vector rows removed, Phase 3a/3c exits split
- Constitution §IV merged IV.3 CHANGELOG into IV.4 dogfood report
- 16 backlog items landed — see commit range `phase-2-complete..phase-3a-complete`

## Cost / latency on canary repo (LV_DCP)

| Metric | Phase 2 close | Phase 3a close | Delta |
|---|---|---|---|
| cold scan | 0.52s | 0.46s | **−12%** |
| warm scan | 0.28s | 0.25s | **−11%** |
| `ctx mcp doctor` (all 7 checks) | — | 3.15s | new (handshake subprocess spawn ~2s) |
| files / symbols / relations_cached | 156 / 1063 / 2439 | 176 / 1332 / 3193 | +20 / +269 / +754 |

Scan latency improved slightly despite adding ~20 files (new `libs/mcp_ops/` suite + tests) — no regression. Doctor is 3s dominated by MCP stdio handshake; acceptable for a diagnostic tool.

## Eval metrics (Phase 2 thresholds must hold)

| Metric | Threshold | Phase 2 close | Phase 3a close | Result |
|---|---|---|---|---|
| recall@5 files | ≥ 0.85 | 0.891 | **0.891** | same |
| precision@3 files | ≥ 0.60 | 0.620 | **0.620** | same |
| recall@5 symbols | ≥ 0.80 | 0.833 | **0.833** | same |
| impact_recall@5 | ≥ 0.75 | 0.819 | **0.819** | same |

**Zero regression.** All four metrics identical to Phase 2 closing numbers, confirming that Phase 3a did not alter retrieval behaviour (which is the whole point of scoping retrieval rework to Phase 3c).

## Test suite

- **223 passed, 0 failed, 1 deselected** (`requires_claude_cli` marker is excluded by default).
- Phase 2 closed with 157 tests; Phase 3a added 66 tests (+42%). Breakdown:
  - `libs/mcp_ops` tests: claude_cli (8) + install (6) + uninstall (7) + doctor (20) + launchd (6) = 47
  - `_walk_mixed` sub-walk A/B tests: 6
  - `Graph.has_node`: 3
  - `.env.*` ignore: 12
  - `daemon` last_scan_at: 3
  - `ctx scan` abs path: 1
  - `test_version`: 3 (replaced tautological tests in T1 fix)
  - minus deleted: old `tests/unit/mcp/test_install.py` (8 tests removed — settings.json writer no longer exists)
  - plus `tests/integration/test_mcp_install_real.py::test_real_install_uninstall_roundtrip` (1, marker-gated, not in default count)
- `make lint typecheck test` clean — ruff all checks passed, mypy strict 0 issues.

## Known issues

- **`ctx mcp doctor` check 4 (config.yaml) shows "0 projects registered"** after each project's install in the dogfood run. That's because `ctx scan` does not auto-register scanned projects into `~/.lvdcp/config.yaml` — registration requires explicit `ctx watch add <path>`. Not a Phase 3a bug; it's a UX observation for Phase 3b (the dashboard should either show the discrepancy or auto-register scanned projects).
- **Doctor `mcp handshake` check adds ~2s to `ctx mcp doctor`** due to MCP server subprocess spawn + stdio handshake. Acceptable but worth revisiting if doctor becomes a hot path.
- **`requires_claude_cli` integration test** runs the real `claude mcp add/remove` roundtrip against the user's actual `claude` CLI. Passed on dev machine. Will be skipped in CI (no claude binary) — documented limitation.

## Commit range

```
git log --oneline phase-2-complete..phase-3a-complete
```

## Next up: Phase 3b

See [docs/superpowers/specs/2026-04-11-phase-3a-design.md § 11 Dependencies on Phase 3b/3c](../superpowers/specs/2026-04-11-phase-3a-design.md#11-dependencies-на-phase-3b3c).

Phase 3a delivered the stable install/doctor foundation. Phase 3b (project status dashboard F1.A/B/C + `lvdcp_status` MCP resource) can start immediately. Phase 3c (LLM enrichment + vector search + rerank) has no hard blockers from 3a, but benefits from having 3b's measurement tooling in place first.
