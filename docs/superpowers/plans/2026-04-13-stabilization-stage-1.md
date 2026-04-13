# Stabilization Stage 1 — Mandatory Quality Gates

> Goal: land the first stabilization deliverable with no product-surface
> changes: GitHub Actions must enforce the same quality gates already declared
> by the repository locally.

**Spec:** `docs/superpowers/specs/2026-04-13-stabilization-stage-1-design.md`
**Branch:** `main`

---

## File Map

### New

- `.github/workflows/quality-gates.yml` — CI workflow for lint, typecheck, test, eval

### Modified

- None required for Stage 1 implementation

---

## Task 1: Add quality-gates workflow

**Files:**
- Create: `.github/workflows/quality-gates.yml`

- [x] Add a workflow triggered by `push` and `pull_request`
- [x] Use Python 3.12 and install `uv`
- [x] Install dependencies with `uv sync --all-extras`
- [x] Add four separate jobs:
  - [x] `ruff` runs `uv run ruff check .`
  - [x] `mypy` runs `uv run mypy .`
  - [x] `test` runs `uv run pytest -q -m "not eval and not llm"`
  - [x] `eval` runs `uv run pytest -q -m eval`
- [x] Keep commands identical to local developer commands

**Acceptance:**
- Workflow file is present under `.github/workflows/`
- Commands match repository-local contract exactly
- YAML parses cleanly on inspection

---

## Task 2: Validate and record next slice

- [x] Inspect the generated workflow for quoting and trigger correctness
- [x] Run a local sanity readback of the file contents
- [x] Move to Stage 2: repository-wide `ruff` cleanup
