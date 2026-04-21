# Eval reports + datasets

This directory is the persistent home for:

- **Per-phase eval reports** — point-in-time snapshots captured during
  retrieval pipeline work (file name = `YYYY-MM-DD-<phase>.md`).
- **Gold dataset documentation** — schema, conventions, and curation
  rules for the YAML files under [`../../tests/eval/datasets/`](../../tests/eval/datasets/).
- **Failure analyses** — when a query class trips the harness and
  warrants a writeup (e.g. `3c2-failure-analysis.md`).

## Quick links

- **How to run the harness**: [`../operations/eval.md`](../operations/eval.md)
- **CI gate**: [`../operations/ci-eval.md`](../operations/ci-eval.md)
- **Dataset schema + conventions**: [`gold-datasets.md`](gold-datasets.md)
- **Constitution contract**: [`../adr/002-eval-harness.md`](../adr/002-eval-harness.md)
- **Current baseline**: [`../../tests/eval/baselines/main.json`](../../tests/eval/baselines/main.json)

## Gold datasets (at a glance)

Four curated YAML files under `tests/eval/datasets/`, each probing a
distinct failure mode. Sizes are floors (SC-005) — enforced by
[`test_shipped_gold_datasets_meet_size_floors`](../../tests/eval/test_dataset_schema.py).

| File | Floor | What it probes |
|---|---|---|
| `rare_symbols.yaml` | 20 | Private helpers, UUID/hash-like names |
| `close_siblings.yaml` | 15 | Near-synonym disambiguation (sync vs async, v1 vs v2) |
| `graph_expansion.yaml` | 15 | Seed symbol → expected callers/callees/refs |
| `edit_tasks.yaml` | 30 | Realistic edit tasks with expected-touch files |

Full schema + curation rules → [`gold-datasets.md`](gold-datasets.md).

## Phase reports (historical)

Reports committed here are **immutable snapshots** — they anchor the
claims ADR-002 makes about retrieval quality at each milestone. Don't
edit older reports when numbers change; capture a new dated report
instead.

Recent phases:

- `2026-04-13-phase5-final.md` — phase 5 freeze (recall@5 = 0.964 on sample_repo)
- `2026-04-13-multiproject-phase5-final.md` — polyglot phase 5
- `2026-04-21-aider-baseline-comparison.md` — vs Aider repomap baseline
- `2026-04-16-vector-vs-fts-sample-repo.md` — retrieval mode ablation

## Running a new phase report

```bash
# 1. Save a snapshot.
uv run ctx eval run tests/eval/fixtures/sample_repo \
  --queries tests/eval/queries.yaml \
  --impact-queries tests/eval/impact_queries.yaml \
  --save-to eval-results/ \
  --output docs/eval/$(date -u +%Y-%m-%d)-phaseN-final.md

# 2. Diff against the previous phase to highlight what moved.
uv run ctx eval compare \
  eval-results/<previous-snapshot>.json \
  eval-results/<new-snapshot>.json \
  >> docs/eval/$(date -u +%Y-%m-%d)-phaseN-final.md
```

The per-query table inside the markdown report is the richest artifact;
read the rows where `recall@5 = 0.000` first when hunting regressions.
