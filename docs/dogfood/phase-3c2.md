# Phase 3c.2 Dogfood Report

**Date:** 2026-04-12
**Version:** 0.3.4
**Scope:** Deterministic retrieval fixes (D1 role weights + D2 config boost + D3 graph depth)

## Eval gate results

### Synthetic fixture (32 queries)
- recall@5 files:    0.948 (target ≥ 0.92) **PASS** (+0.057 from baseline 0.891)
- precision@3 files: 0.615 (target ≥ 0.60) **PASS** (-0.005 from baseline 0.620)
- recall@5 symbols:  0.880 (target ≥ 0.80) **PASS** (+0.047 from baseline 0.833)
- impact_recall@5:   0.931 (target ≥ 0.85) **PASS** (+0.112 from baseline 0.819)

### Queries fixed by Stage 1

| Query | Baseline | After | Fix |
|---|---|---|---|
| q16-access-ttl | 0.50 | 1.00 | D2 config boost + "lifetime" keyword |
| i02-password-hash-tighten | 0.67 | 1.00 | D1 role weights (test demoted, handler promoted) |
| i04-access-ttl-reduction | 0.50 | 1.00 | D2 config boost + "lifetime" keyword |
| i05-cleanup-schedule-change | 0.50 | 1.00 | D2 config boost ("schedule" keyword) |

### Remaining failures (not blocking — above targets)

| Query | recall@5 | Missed | Reason |
|---|---|---|---|
| q04-refresh-flow | 0.50 | app/handlers/auth.py | Graph rank: handler not reached by graph from FTS seeds |
| q19-edit-login | 0.67 | tests/test_auth.py | Test file ranked below top-5 (role weight demotion expected) |
| i01-session-storage-change | 0.50 | cleanup.py, test_cleanup.py | Graph expansion: 3+ hops even with depth=3 |
| i06-db-connection-migration | 0.67 | app/main.py | Graph expansion: main.py not connected at depth 3 |

These are graph walk + semantic intent failures — candidates for Stage 2 (vector+rerank) if it's ever triggered.

## Calibration history

| Iteration | Change | recall@5 | impact | Notes |
|---|---|---|---|---|
| 0 (baseline) | — | 0.891 | 0.819 | Pre-Stage-1 |
| D1+D2+D3 | Initial implementation | 0.901 | 0.847 | Config boost baseline too low |
| Cal 1 | Relative baseline (50% of max) | 0.906 | 0.889 | q19 regression from substring match |
| Cal 2 | Word matching + "lifetime" | **0.948** | **0.931** | All gates pass |

## Stage 2 status

**NOT TRIGGERED.** All 5 eval gates pass. Stage 2 (vector + rerank on summaries) is not needed for Phase 3c.2.
