# Running the eval harness — operations guide

Concrete recipes for the three eval flows LV_DCP ships. See
[`docs/operations/ci-eval.md`](ci-eval.md) for the PR gate and
[`docs/adr/002-eval-harness.md`](../adr/002-eval-harness.md) for the
contract that motivates all of this.

## The three flows

| Flow | Command | Purpose | Cost |
|---|---|---|---|
| **IR smoke** | `make eval` | `pytest -m eval` — fixture-based IR metrics | Free, ~3 min |
| **LLM judge** | `make eval-full` | `pytest -m "eval and llm"` — IR + RAGAS | Requires `ANTHROPIC_API_KEY`, < $0.50 |
| **Ad-hoc run** | `ctx eval run <project> --queries <yaml>` | Human-facing report on any indexed project | Free (no LLM) |

## Local quickstart

```bash
# Fixture-based IR eval (runs on every PR via CI already).
make eval

# Ad-hoc run against an indexed project, markdown report to stdout.
uv run ctx eval run tests/eval/fixtures/sample_repo \
  --queries tests/eval/queries.yaml \
  --impact-queries tests/eval/impact_queries.yaml

# Save a snapshot for later comparison.
uv run ctx eval run tests/eval/fixtures/sample_repo \
  --queries tests/eval/queries.yaml \
  --save-to eval-results/

# List saved runs (newest first).
uv run ctx eval history --dir eval-results/

# Diff two snapshots.
uv run ctx eval compare eval-results/before.json eval-results/after.json
```

## Running the LLM-judge path

The RAGAS adapter (`libs/eval/ragas_adapter.py`) adds context-precision,
context-recall, and faithfulness scores on top of the IR metrics. It
requires an Anthropic API key and is **not** in CI — see the ADR for the
cost reasoning.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make eval-full
```

The first run populates the deterministic cache
(`libs/eval/ragas_adapter.py` — SHA256 over content); subsequent identical
runs hit the cache and cost nothing. Expected cost for the full fixture
set: **< $0.50** on Claude Haiku (SC-002).

## Reading a report

`ctx eval run` emits Markdown by default. Key sections:

1. **Aggregate IR metrics** — recall@5 / precision@3 / recall@5 symbols /
   MRR / impact_recall@5. These drive the CI gate.
2. **LLM-judge metrics** — only present when the adapter ran.
   context_precision / context_recall / faithfulness in [0, 1]; higher
   is better. Cache hit/miss counts are at the end.
3. **Per-query table** — one row per query with retrieved files count,
   recall@5, and misses. Scan this when a regression fires; the row
   with the biggest delta is usually the one to investigate.

For machine-readable output use `--json` — same shape as saved
snapshots (JSON schema documented in
[`libs/eval/history.py`](../../libs/eval/history.py) via `report_to_dict`).

## Updating the CI baseline

Full flow documented in [ci-eval.md](ci-eval.md). TL;DR for local
reproduction:

```bash
# Regenerate tests/eval/baselines/main.json from the current retriever.
uv run python - <<'PY'
import json
from pathlib import Path
from libs.eval.history import report_to_dict
from libs.project_index.index import ProjectIndex
from tests.eval.run_eval import run_eval, FIXTURE_REPO

def retrieve(q, m, p):
    with ProjectIndex.open(p) as idx:
        r = idx.retrieve(q, mode=m, limit=10)
        return list(r.files), list(r.symbols)

report = run_eval(retrieve)
Path("tests/eval/baselines/main.json").write_text(
    json.dumps(report_to_dict(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY
```

## Gold datasets

Four curated sets under [`tests/eval/datasets/`](../../tests/eval/datasets/)
probe distinct failure modes:

- `rare_symbols.yaml` — private/UUID/hash-like needles
- `close_siblings.yaml` — near-synonym disambiguation
- `graph_expansion.yaml` — callers/callees neighborhoods
- `edit_tasks.yaml` — realistic edit tasks with expected-touch files

Size floors (SC-005) are enforced by
[`tests/eval/test_dataset_schema.py`](../../tests/eval/test_dataset_schema.py)
in the default (non-eval) test suite. Full schema + curation rules in
[`docs/eval/gold-datasets.md`](../eval/gold-datasets.md).

## Troubleshooting

- **`error: no cache for project X`** — run `ctx scan X` first.
- **`make eval-full` is silent** — ensure `ANTHROPIC_API_KEY` is
  exported; the adapter only runs when the env is set (T014 fixtures).
- **CI gate failing but local passes** — the CI gate uses the committed
  `tests/eval/baselines/main.json`; your local run might be against a
  stale index. Re-scan the fixture (`ctx scan tests/eval/fixtures/sample_repo`)
  and rerun.

## Cross-reference

- Spec: [`specs/006-ragas-promptfoo-eval/spec.md`](../../specs/006-ragas-promptfoo-eval/spec.md)
- Constitution: [`docs/adr/002-eval-harness.md`](../adr/002-eval-harness.md)
- Harness source: [`libs/eval/`](../../libs/eval/)
- CI gate: [`docs/operations/ci-eval.md`](ci-eval.md)
