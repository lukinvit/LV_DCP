# Phase 7A — Real-Project Eval Reproducibility

**Spec:** `docs/superpowers/specs/2026-04-13-phase-7a-eval-reproducibility-design.md`

---

## Task 1: Build a shared advisory eval helper

- [x] Add a helper for loading real-project fixtures
- [x] Add explicit project-map loading from default path or env override
- [x] Return skipped-project reasons alongside recall metrics

## Task 2: Rebuild polyglot and multi-project runners on top

- [x] Refactor `run_polyglot_eval.py` to use the shared helper
- [x] Add `run_multiproject_eval.py` using the same helper
- [x] Fix partial-availability threshold handling in the polyglot pytest wrapper

## Task 3: Add manual report tooling and docs

- [x] Add a reusable report generator for advisory eval suites
- [x] Add `polyglot` and `multiproject` report scripts
- [x] Document the local project-map setup and manual workflow

## Task 4: Validate

- [x] Run targeted tests for the new helper and polyglot wrapper
- [x] Run `ruff` and `mypy` on touched files
- [x] Run `pytest -q -m eval` to confirm advisory behavior remains correct
