# Stabilization Stage 3 — Restore Green Mypy Baseline

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Stabilization Stage 2
**Version target:** 0.6.1

## 1. Goal

Bring the repository back to a fully green `mypy` baseline while preserving
existing runtime behavior.

**Litmus test:** `uv run mypy .` exits 0 on the repository state produced by
this stage.

## 2. Problem

The repository declares strict typing in `pyproject.toml`, but the current
baseline is red due to a combination of:

- missing generic parameters on container types
- narrow retrieval-specific typing gaps
- third-party library typing gaps (`pymorphy3`)
- functions returning heterogeneous dict payloads without shared type aliases

This stage restores the declared type contract. It does not loosen global mypy
settings to make the problem disappear.

## 3. Scope

### In scope

- fix concrete mypy errors currently reported by `uv run mypy .`
- add narrow type aliases or `TypedDict` structures where repeated dict shapes exist
- fix stale or incorrect `type: ignore`
- add targeted mypy overrides only for genuine third-party typing gaps

### Out of scope

- broad `Any`-ification of APIs
- refactors driven only by aesthetics
- runtime warning cleanup unrelated to typing

## 4. Design Rules

1. Prefer real types over `Any`.
2. Prefer local aliases/`TypedDict` over repeated bare `dict`.
3. Keep suppressions narrow and justified.
4. If touching user-modified retrieval files, limit changes strictly to typing
   and preserve retrieval logic exactly.

## 5. Acceptance Criteria

1. `uv run mypy .` passes.
2. Global mypy strictness remains unchanged.
3. No broad `ignore_missing_imports` expansion is added beyond targeted need.
4. Non-eval tests continue to pass after typing fixes.
