# Phase 9 — Project Copilot Wrapper

**Spec:** `docs/superpowers/specs/2026-04-13-phase-9-project-copilot-wrapper-design.md`

---

## Task 1: Define wrapper command surface

- [ ] Choose the first stable command group (`ctx project ...` or equivalent)
- [ ] Keep the surface user-oriented rather than MCP-oriented

## Task 2: Build orchestration over existing primitives

- [ ] Reuse `status`, `scan`, `wiki`, `pack`, and `explain`
- [ ] Add degraded-mode explanations for missing prerequisites

## Task 3: Validate

- [ ] Add wrapper CLI tests
- [ ] Run targeted retrieval/CLI tests
- [ ] Run `ruff` and `mypy`
