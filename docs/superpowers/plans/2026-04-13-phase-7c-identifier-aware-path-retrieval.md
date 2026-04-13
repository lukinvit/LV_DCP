# Phase 7C — Identifier-Aware Path Retrieval

**Spec:** `docs/superpowers/specs/2026-04-13-phase-7c-identifier-aware-path-retrieval-design.md`

---

## Task 1: Add shared identifier tokenization

- [x] Add a retrieval helper for identifier/path token splitting
- [x] Reuse it in symbol lookup

## Task 2: Strengthen FTS path matching

- [x] Add path alias text during FTS indexing
- [x] Expand FTS query terms for identifier-style input
- [x] Add targeted FTS tests for snake_case and CamelCase retrieval

## Task 3: Add bounded path-token boost in pipeline

- [x] Add basename/parent overlap boost for already-scored candidates
- [x] Add targeted heuristic tests

## Task 4: Validate

- [x] Run targeted retrieval unit tests
- [x] Run `ruff` and `mypy`
- [x] Run `pytest -q -m eval`
