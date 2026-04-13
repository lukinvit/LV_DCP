# Phase 7A — Real-Project Eval Reproducibility

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Stabilization 0.6.1
**Version target:** 0.6.x

## 1. Goal

Make multi-project and polyglot eval **explicit, reproducible, and honest**
without pretending they are CI-gated on every machine.

**Litmus test:** a contributor can tell, from repository-native tooling alone:

- which evals are mandatory vs advisory
- how real-project eval projects are resolved on their machine
- why a given project was skipped
- how to produce a markdown report for manual review

## 2. Problem

The current real-project eval surface is under-specified:

- polyglot eval depends on registered local projects but hides most of that
  resolution logic in one runner
- multi-project eval is represented in fixtures and docs, but its execution path
  is mostly a legacy report shell script
- skip behavior is too opaque
- if only a subset of projects is available, the current polyglot test can
  incorrectly fail missing per-project thresholds instead of treating the run as
  partial/advisory

This is not a retrieval-quality problem. It is an eval-ops problem.

## 3. Scope

### In scope

- shared real-project eval helper for fixture loading, project-map resolution,
  skip reasons, and report aggregation
- explicit local project-name mapping via a documented yaml file
- one runner for polyglot eval and one runner for multi-project eval using the
  shared helper
- markdown report generation for manual/advisory review
- repository docs that explain the advisory/manual status

### Out of scope

- downloading or vendoring external sample repositories
- promoting real-project eval to mandatory CI
- changing synthetic eval thresholds
- changing retrieval ranking logic

## 4. Design

### 4.1 Real-project eval remains advisory

Synthetic eval stays the only mandatory CI-gated retrieval contract.
Multi-project and polyglot eval are **manual/advisory** because they depend on
real repositories outside this repo.

### 4.2 Explicit local project map

Support an optional yaml file at:

- `~/.lvdcp/eval-project-map.yaml`
- or override via `LVDCP_EVAL_PROJECT_MAP`

Schema:

```yaml
projects:
  GoTS_Project: my-real-go-ts-repo
  PythonTS_Project: my-real-python-ts-repo
  Project_Large: my-large-repo
```

If no mapping is provided, the generic fixture name is used as the expected
registered directory name.

### 4.3 Shared report model

The helper should return:

- per-query results
- per-project recall
- overall recall
- skipped projects with concrete reasons

### 4.4 Partial availability

If some advisory projects are unavailable:

- available projects are evaluated
- missing projects are reported as skipped
- per-project thresholds apply only to projects actually present in the report
- if no projects are available, the pytest wrapper skips with a reason summary

### 4.5 Report scripts

Repository scripts should generate markdown reports under `docs/eval/` for:

- polyglot eval
- multi-project eval

Both reports should include skipped projects and the mapping file path used.

## 5. Acceptance Criteria

1. Polyglot eval no longer fails because a thresholded project is missing from
   the local machine.
2. Multi-project and polyglot eval share the same resolution logic.
3. A documented local project-map flow exists.
4. Manual report commands exist for both advisory eval suites.
