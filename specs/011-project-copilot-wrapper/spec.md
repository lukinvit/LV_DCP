# spec-011: Project Copilot Wrapper

**Status:** Draft → In progress 2026-04-23
**Phase:** 9
**Owner:** Vladimir Lukin
**Design doc:** `docs/superpowers/specs/2026-04-13-phase-9-project-copilot-wrapper-design.md`

## 1. Summary

Add a user-facing `ctx project` command group that orchestrates the
existing low-level LV_DCP primitives (`scan`, `pack`, `wiki`, `status`,
`explain`) into single high-level actions. The goal is that a user — or
a foreign agent (Claude Code, Cursor, a shell script) — can ask one
project-facing question and get a sane answer without knowing which
primitive to call in which order.

## 2. Problem

LV_DCP today exposes the right primitives but not a project-aware
orchestrator over them:

- Users have to know that `pack` needs a fresh index first.
- Wiki freshness has to be checked separately from pack quality.
- Degraded states (Qdrant down, no wiki, stale scan) surface as partial
  results or stack traces instead of actionable messages.
- The `lvdcp_pack` MCP tool is smart for AI callers but has no
  equivalent for humans on the CLI.

## 3. Non-goals

- Replacing `lvdcp_scan`, `lvdcp_pack`, `lvdcp_status`, `lvdcp_explain`,
  or `ctx wiki …`. The wrapper composes them, it does not shadow them.
- Multi-step *code edit* workflows. That belongs to a later phase.
- A general-purpose autonomous coding agent.

## 4. Scope

### In scope

- New command group `ctx project` with four subcommands:
  `check`, `refresh`, `wiki`, `ask`.
- A small orchestration library `libs/copilot/` that the CLI is a thin
  Typer wrapper over (single-writer discipline: CLI → library → primitives).
- Capability detection that distinguishes the four canonical failure
  modes — (a) not scanned, (b) wiki not generated, (c) Qdrant /
  embeddings unavailable, (d) ambiguous retrieval — and surfaces each as
  a human-readable action item.
- Unit tests against the library + Typer CLI tests via `CliRunner`.

### Out of scope (this phase)

- Auto-firing `ctx scan` during `ask` unless explicitly opted in via
  `--refresh`. We suggest, we do not silently mutate the index.
- An MCP tool wrapper around the copilot layer. MCP callers already
  compose `lvdcp_status + lvdcp_pack` themselves; we only gate the CLI
  surface in this phase.
- Cross-project queries. `ctx project` is strictly single-project; the
  cross-project surface stays under `ctx wiki cross-project`.

## 5. User stories

- **US-1 (check):** *As a user, I want `ctx project check <path>` to tell
  me in one glance whether the project is scanned, whether the index is
  stale, whether the wiki is fresh, and whether full-mode retrieval is
  available.*
- **US-2 (refresh):** *As a user, I want `ctx project refresh <path>`
  to run `scan` then `wiki update` in one call, so I don't have to
  remember to update both after a large change.*
- **US-3 (wiki):** *As a user, I want `ctx project wiki <path>` to print
  wiki freshness; `--refresh` should regenerate dirty articles.*
- **US-4 (ask):** *As a user, I want `ctx project ask <path> "question"`
  to behave like the MCP `lvdcp_pack` tool: print a ranked context pack
  and flag degraded modes (ambiguous retrieval → suggest `explain` or
  rephrase; stale index → suggest `refresh`).*

## 6. Success criteria

- SC-1: Each `ctx project` subcommand exits non-zero only on hard errors
  (path doesn't exist, permission denied). Degraded modes return a zero
  exit with an explanatory message.
- SC-2: `ctx project ask` reproduces the same top-10 files that
  `lvdcp_pack` returns for the same query on the same project.
- SC-3: `ctx project check` runs in under 2 s on the LV_DCP monorepo
  (< 500 ms for the common warm-index path).
- SC-4: 100 % of tests added in this phase pass `ruff` + `mypy --strict`
  without new ignores.

## 7. Deliverables

- `libs/copilot/__init__.py` — public surface.
- `libs/copilot/orchestrator.py` — `check_project`, `refresh_project`,
  `refresh_wiki`, `ask_project` library functions.
- `libs/copilot/models.py` — pydantic DTOs: `CopilotCheckReport`,
  `CopilotRefreshReport`, `CopilotAskReport`, `DegradedMode`.
- `apps/cli/commands/project_cmd.py` — `ctx project {check,refresh,wiki,ask}`.
- Wiring in `apps/cli/main.py`.
- Tests: `tests/unit/copilot/`, `tests/unit/cli/test_project_cmd.py`.

## 8. Risks

- **Drift from `lvdcp_pack`:** if the copilot's `ask` path implements
  retrieval in parallel with `lvdcp_pack`, the two surfaces will
  diverge. Mitigation: `ask_project` *calls* `apps.mcp.tools.lvdcp_pack`
  under the hood rather than re-implementing retrieval.
- **Scope creep:** the plan says "check, refresh, wiki, ask" — keep to
  those four. Any other subcommand goes to a follow-up spec.
- **Config drift:** copilot should not create a new config layer. It
  reads the same `~/.lvdcp/config.yaml` as every other primitive.
