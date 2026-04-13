# Stabilization Stage 2 — Restore Green Ruff Baseline

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Stabilization Stage 1
**Version target:** 0.6.1

## 1. Goal

Bring the repository back to a fully green `ruff` baseline without changing
product behavior.

**Litmus test:** `uv run ruff check .` exits 0 on the repository state produced
by this stage.

## 2. Problem

The repository declares strict linting, but the current baseline is red due to
a mix of:

- low-risk cleanup opportunities
- design-shape warnings that should be acknowledged explicitly
- false-positive or context-specific warnings around Unicode lexical data,
  SQL string construction, and async/path usage in controlled contexts

The correct response is not a blanket ignore. It is a targeted normalization:
fix real issues, add narrow `noqa` only where the current design is intentional.

## 3. Scope

### In scope

- import ordering and unused imports
- trivial code simplifications
- logging instead of silent `except/pass`
- narrow function-level or line-level `noqa` for intentional signatures
- narrow per-file ignores for legitimate Unicode lexical data
- test cleanup needed to satisfy `ruff`

### Out of scope

- full type stabilization (`mypy`)
- retrieval behavior changes unrelated to lint findings
- large refactors done only to satisfy metrics like branch count

## 4. Design Rules

1. Prefer code fixes over ignores when the issue is real and low-risk.
2. Prefer line-level or function-level `noqa` over global config changes.
3. Do not refactor public APIs just to reduce argument count if the call shape
   is already the correct domain model.
4. Do not rewrite Russian lexical dictionaries to dodge Unicode warnings; use
   explicit lint allowances for those files.
5. Avoid touching unrelated dirty files unless the fix is trivial and clearly
   compatible with the user's current changes.

## 5. Acceptance Criteria

1. `uv run ruff check .` passes.
2. No new broad global ignores are added.
3. All added suppressions are narrow and justified by local context.
4. Behavior-facing code paths remain unchanged except for improved logging in
   degraded mode.
