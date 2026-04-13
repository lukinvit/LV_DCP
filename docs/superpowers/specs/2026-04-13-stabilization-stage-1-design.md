# Stabilization Stage 1 — Mandatory Quality Gates

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Phase 6 complete (`0.6.0`)
**Version target:** 0.6.1

## 1. Goal

Convert LV_DCP from a feature-rich but locally enforced project into a repository
with **mandatory, automated quality gates**. Stage 1 does not add user-facing
features. It makes the declared engineering contract executable on every PR.

**Litmus test:** A contributor opening a PR gets the same four required checks
that the maintainer runs locally:

1. `uv run ruff check .`
2. `uv run mypy .`
3. `uv run pytest -q -m "not eval and not llm"`
4. `uv run pytest -q -m eval`

## 2. Problem

LV_DCP already declares strict quality tooling in `pyproject.toml`, but the
repository currently relies on manual local discipline. This creates three
problems:

1. The repo can claim a strict bar while `main` drifts red.
2. Retrieval quality gates exist, but are not automatically enforced per PR.
3. Contributors cannot tell which checks are mandatory versus advisory.

## 3. Scope

Stage 1 is deliberately narrow.

### In scope

- Add GitHub Actions workflow(s) for the four mandatory checks
- Keep the commands identical to local developer commands
- Run on push and pull request for the default branch workflow
- Use Python 3.12 and `uv`
- Document the workflow's purpose in repository-native planning artifacts

### Out of scope

- Fixing existing `ruff` or `mypy` failures
- Changing retrieval thresholds
- Adding caching or matrix builds
- Release automation
- VS Code, UI, MCP, or retrieval behavior changes

## 4. Design

### 4.1 Workflow shape

One workflow, `quality-gates.yml`, with four jobs:

- `ruff`
- `mypy`
- `test`
- `eval`

The jobs are intentionally separate so failures are attributable and can be
re-run independently in GitHub UI.

### 4.2 Environment

- `runs-on: ubuntu-latest`
- `actions/checkout@v4`
- `actions/setup-python@v5` with Python 3.12
- Install `uv`
- Run `uv sync --all-extras`

We install all extras because the test and eval surface spans optional modules
such as embeddings and wiki integration.

### 4.3 Command contract

The workflow must run the exact commands already used locally, not variants:

```bash
uv run ruff check .
uv run mypy .
uv run pytest -q -m "not eval and not llm"
uv run pytest -q -m eval
```

This keeps CI and local development aligned and avoids a second hidden test
contract.

### 4.4 Failure behavior

Any failing job blocks the PR. Stage 1 intentionally makes current repository
health visible even if this means the first CI run is red.

That is a feature, not a defect: stabilization work starts by exposing the real
state of the repository.

## 5. Acceptance Criteria

1. `.github/workflows/quality-gates.yml` exists.
2. The workflow triggers on `push` and `pull_request`.
3. All four mandatory checks run as separate jobs.
4. The commands match local developer commands exactly.
5. The workflow does not modify repository behavior outside CI.

## 6. Risks

### Risk: CI immediately goes red

Expected. This stage is the gate-enablement step; Stage 2 and Stage 3 will
bring the repository back to green.

### Risk: dependency install is slow

Accepted for Stage 1. Speed optimizations are secondary to correctness.

## 7. Follow-up Stages

- **Stage 2:** Restore green `ruff`
- **Stage 3:** Restore green `mypy`
- **Stage 4:** Harden degraded-mode runtime paths and remove async warnings
