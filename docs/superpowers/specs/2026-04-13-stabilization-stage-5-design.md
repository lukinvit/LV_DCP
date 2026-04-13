# Stabilization Stage 5 — Status Sync and Release Prep

**Status:** Implemented 2026-04-13
**Owner:** Vladimir Lukin
**Follows:** Stabilization Stage 4
**Version target:** 0.6.1

## 1. Goal

Synchronize the repository's public status surfaces with the now-green quality
baseline and prepare a coherent `0.6.1` stabilization release.

**Litmus test:** a reader opening the repository can infer the actual state
without contradiction:

- version markers say `0.6.1`
- README reflects current metrics and test counts
- the release note explains what changed in stabilization

## 2. Problem

The repository was reporting a mix of historical and current states:

- `0.6.0` version markers after stabilization work already landed
- outdated retrieval metrics in README
- outdated test counts in README
- phase-complete messaging without mentioning the stabilization pass

## 3. Scope

### In scope

- bump canonical version markers to `0.6.1`
- update README metrics and test counts to current green baseline
- add a short release note for the stabilization release

### Out of scope

- rewriting historical implementation plans
- changing evaluation thresholds
- adding release automation tooling

## 4. Design Rules

1. Prefer updating canonical public surfaces only.
2. Preserve historical docs as historical records unless they actively mislead.
3. Release notes should describe stabilization work, not re-document the entire project.

## 5. Acceptance Criteria

1. Canonical version markers read `0.6.1`.
2. README status section matches the current tested baseline.
3. A release note exists for `0.6.1`.
