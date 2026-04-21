# Gold datasets for retrieval eval

LV_DCP ships four curated gold datasets under [`tests/eval/datasets/`](../../tests/eval/datasets/).
Each file is a YAML list of `GoldQuery` entries validated by the Pydantic schema in
[`libs/eval/dataset_schema.py`](../../libs/eval/dataset_schema.py).

| File | Floor (SC-005) | Purpose |
|---|---|---|
| `rare_symbols.yaml` | 20 | Private helpers, constants, hash-like / UUID-like names — needles in the haystack |
| `close_siblings.yaml` | 15 | Near-synonym disambiguation (sync vs async, v1 vs v2, before/after refactor) |
| `graph_expansion.yaml` | 15 | Seed symbol → expected top-K callers/callees/references (graph mode) |
| `edit_tasks.yaml` | 30 | Realistic edit tasks — the files an agent must touch to do them right |

## Schema (summary)

```yaml
queries:
  - id: unique-slug
    text: natural-language query or symbol name
    mode: navigate | edit | graph
    expected:
      files: [list, of, relative, paths]
      symbols: [optional, dotted, symbol.paths]
      answer_text: optional LLM-judge reference answer
    notes: optional human-readable hint
    tags: [optional, list, of, tags]
```

Full schema lives in [`libs/eval/dataset_schema.py`](../../libs/eval/dataset_schema.py); the
authoritative validator is [`tests/eval/test_dataset_schema.py`](../../tests/eval/test_dataset_schema.py),
which runs in the default CI profile and guards the floors above.

## How to add queries

1. Pick the dataset that matches the shape of what you want to probe. If the query
   doesn't fit the four archetypes, open an issue before adding a new file —
   dataset proliferation hurts cross-run comparability.
2. Give the new entry a stable `id` (`slug-what-it-tests`). IDs never change once
   merged — the history layer keys on them.
3. Populate `expected.files` with paths relative to the repo root. For LV_DCP-wide
   datasets, these are paths in this repo (self-hosting). For project-specific
   datasets, document the expected repo in a top-of-file comment.
4. Prefer under-specifying over over-specifying `expected.symbols`: an empty list is
   valid and tells the harness to score on files only. Don't pin symbols you're not
   confident the retriever should be surfacing.
5. Run the schema test:

   ```bash
   uv run pytest tests/eval/test_dataset_schema.py -q
   ```

## How to use the datasets

```bash
# IR-only, against the indexed self-hosted LV_DCP repo:
uv run ctx eval run . \
  --queries tests/eval/datasets/rare_symbols.yaml \
  --save-to eval-results/

# Add LLM-judge scores (requires ANTHROPIC_API_KEY + eval extras):
make eval-full

# Compare two saved runs:
uv run ctx eval compare eval-results/a.json eval-results/b.json
```

The harness loads a dataset, hands every query to the current retriever, and writes
aggregate + per-query metrics into an `EvalReport`. RAGAS enrichment is optional and
runs through [`libs/eval/runner.py::enrich_with_ragas`](../../libs/eval/runner.py).

## Conventions

- **IDs are stable.** Never rename. If an entry is wrong, mark it `tags: [retired]`
  and add a replacement with a new id — so historical snapshots stay interpretable.
- **Descriptions are independent of the retriever.** Write the query as a user would
  type it, not as the retriever currently happens to understand it.
- **Expected sets are what a senior engineer would approve**, not what the retriever
  currently finds. Gold datasets are a ceiling to aim at, not a mirror of today's
  behavior.
- **One quality per file.** Don't mix rare-symbol queries into `close_siblings.yaml`;
  the whole point is that each dataset probes a distinct failure mode.

## Cross-reference

- Spec: [`specs/006-ragas-promptfoo-eval/spec.md`](../../specs/006-ragas-promptfoo-eval/spec.md) (US4)
- Tasks: [`specs/006-ragas-promptfoo-eval/tasks.md`](../../specs/006-ragas-promptfoo-eval/tasks.md) (T020–T026)
- Harness: [`libs/eval/runner.py`](../../libs/eval/runner.py)
- Success criteria: SC-005 (dataset sizes) in the spec
