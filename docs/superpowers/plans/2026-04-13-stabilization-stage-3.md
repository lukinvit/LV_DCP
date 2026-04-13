# Stabilization Stage 3 — Restore Green Mypy Baseline

**Spec:** `docs/superpowers/specs/2026-04-13-stabilization-stage-3-design.md`

---

## Task 1: Capture and group mypy failures

- [x] Run `uv run mypy .`
- [x] Group failures by category:
  - [x] bare generic containers
  - [x] retrieval typing gaps
  - [x] third-party typing gaps
  - [x] DTO/dict payload mismatches

## Task 2: Fix code-level type errors

- [x] Introduce local aliases or `TypedDict` for repeated dict payloads
- [x] Fix retrieval pipeline typing without changing scoring behavior
- [x] Resolve obsidian/status/embeddings container typing
- [x] Add narrow third-party override only where necessary

## Task 3: Validate baseline

- [x] Run `uv run mypy .`
- [x] Run non-eval tests if touched areas are exercised broadly
- [x] Stop only when mypy is green or the next blocker requires a dedicated slice
