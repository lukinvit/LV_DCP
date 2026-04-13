# Stabilization Stage 4 — Runtime Warning Hardening

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Stabilization Stage 3
**Version target:** 0.6.1

## 1. Goal

Eliminate the currently known runtime warning classes emitted by the test suite
without weakening optional subsystem behavior.

**Litmus test:** non-eval and eval test runs no longer emit the known LV_DCP-side
warnings for:

- `coroutine '_do_embed' was never awaited`
- Qdrant client/server compatibility warning
- local Qdrant payload-index warning

## 2. Problem

The repository is now green on `ruff`, `mypy`, and tests, but not yet quiet.
Warnings matter here because they indicate:

- async boundary misuse in best-effort embedding paths
- operational mismatch between Qdrant client and server defaults
- noisy test output that hides real failures

## 3. Scope

### In scope

- harden `embed_project_files()` async execution path
- avoid creating unused payload indexes for local in-memory Qdrant
- disable compatibility checks where LV_DCP intentionally tolerates degraded mode

### Out of scope

- redesigning the embeddings subsystem
- changing retrieval ranking logic
- production deployment policy beyond current local-first behavior

## 4. Design Rules

1. Preserve best-effort behavior: embedding failures must not break scanning.
2. Fix root causes rather than filtering warnings in pytest.
3. Keep the implementation local to embeddings/Qdrant code paths.

## 5. Acceptance Criteria

1. The async embedding path does not leak unawaited coroutine warnings.
2. Local/in-memory Qdrant tests do not emit payload-index warnings.
3. Normal test runs do not emit Qdrant compatibility warnings from LV_DCP code paths.
