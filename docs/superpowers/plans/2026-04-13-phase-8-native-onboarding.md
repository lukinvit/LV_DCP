# Phase 8 — Native Onboarding

**Spec:** `docs/superpowers/specs/2026-04-13-phase-8-native-onboarding-design.md`

---

## Task 1: Add `ctx setup` orchestration command

- [x] Add a new top-level `ctx setup` command
- [x] Reuse existing MCP, scan, wiki, watch, and UI primitives
- [x] Keep MCP/wiki/service steps best-effort where possible

## Task 2: Add explicit readiness reporting

- [x] Report `base mode` vs `full mode`
- [x] Report missing `Qdrant + embeddings` for full retrieval
- [x] Report missing `Claude CLI` for wiki generation

## Task 3: Validate

- [x] Add CLI tests for `ctx setup`
- [x] Run targeted CLI tests
- [x] Run `ruff` and `mypy`
