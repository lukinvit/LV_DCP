# Phase 7C — Directory-Aware Path Boosting

**Spec:** `docs/superpowers/specs/2026-04-14-phase-7c-directory-aware-path-boosting-design.md`
**Status:** Implemented

## Task 1: Cover deeper path overlap with tests

- [x] Add unit tests for ancestor-directory overlap
- [x] Assert the new boost remains bounded
- [x] Assert no-overlap candidates remain unchanged

## Task 2: Implement bounded ancestor-aware scoring

- [x] Extend path-token boosting to consider deeper ancestor directories
- [x] Keep parent and basename weighting stronger than ancestor weighting
- [x] Preserve the "already-scored candidates only" invariant

## Task 3: Validate the slice

- [x] Run `uv run ruff check .`
- [x] Run `uv run mypy .`
- [x] Run targeted retrieval unit tests
- [x] Run default non-eval tests
- [x] Run eval tests
