# Stabilization Stage 4 — Runtime Warning Hardening

**Spec:** `docs/superpowers/specs/2026-04-13-stabilization-stage-4-design.md`

---

## Task 1: Fix embedding async boundary

- [x] Inspect `embed_project_files()` sync wrapper
- [x] Remove unawaited coroutine warning path
- [x] Preserve best-effort fallback behavior

## Task 2: Reduce Qdrant warning noise

- [x] Disable compatibility checks for LV_DCP Qdrant client construction
- [x] Skip payload index creation for local in-memory Qdrant

## Task 3: Validate runtime surface

- [x] Run non-eval tests
- [x] Run eval tests
- [x] Confirm known warning classes are gone
