# Stabilization Stage 2 — Restore Green Ruff Baseline

**Spec:** `docs/superpowers/specs/2026-04-13-stabilization-stage-2-design.md`

---

## Task 1: Remove low-risk lint failures with code fixes

- [x] Clean import ordering and unused imports
- [x] Fix safe simplifications (`SIM*`, `B905`, `F841`, `PLC0206`)
- [x] Replace silent `except/pass` with logged degraded-mode handling where possible

## Task 2: Add narrow acknowledgements for intentional shapes

- [x] Add local `noqa` for intentional many-argument functions in Obsidian/templates/parser internals
- [x] Add local `noqa` for controlled SQL construction where parameters are constant language lists
- [x] Add local lint allowances for intentional Cyrillic lexical sets/dictionaries

## Task 3: Validate baseline

- [x] Run `uv run ruff check .`
- [x] Inspect remaining failures, if any
- [x] Stop only when repository is green or the next blocker requires a separate stabilization slice
