# CI eval gate — operations guide

The `Retrieval Eval (promptfoo gate)` workflow (`.github/workflows/eval.yml`)
runs on every PR that touches retrieval-adjacent code and blocks merges that
regress IR metrics by more than 2 pp versus the committed baseline at
[`tests/eval/baselines/main.json`](../../tests/eval/baselines/main.json).

## Trigger scope

The workflow fires on `pull_request` when any of these paths change:

- `libs/retrieval/**`
- `libs/eval/**`
- `libs/embeddings/**`
- `libs/project_index/**`
- `libs/scanning/**`
- `tests/eval/**`
- `.github/workflows/eval.yml`

Doc-only PRs, infra tweaks, and unrelated library changes intentionally do
not trigger the eval — CI minutes are reserved for changes that can
actually move retrieval numbers.

## What it runs

1. `uv sync --extra eval` — installs `ragas`, `pydantic`, and friends.
2. `uv run ctx scan tests/eval/fixtures/sample_repo` — builds the fixture index.
3. `npx -y promptfoo@latest eval -c tests/eval/promptfoo.config.yaml --output promptfoo-output.json`
   — promptfoo shells out to `ctx eval run --json` and applies the JS
   assertions in the config. Tolerance is 2 pp on every IR metric.

The `promptfoo-output.json` artifact is always uploaded so you can inspect
raw results even on success.

## On failure

The job posts a PR comment enumerating each metric that regressed beyond
tolerance (from `gradingResult.componentResults[].reason`). Example:

```
### Retrieval eval regression detected

One or more retrieval metrics regressed by more than the 2pp tolerance vs
`tests/eval/baselines/main.json`.

- ❌ recall@5 regressed: 0.931 vs baseline 0.964 (tolerance 0.02)
- ❌ impact_recall@5 regressed: 0.889 vs baseline 0.931 (tolerance 0.02)
```

Two options:

1. **Investigate and fix** (preferred). A regression > 2 pp is almost always
   a signal, not noise. Re-run locally with
   `uv run ctx eval run tests/eval/fixtures/sample_repo --queries tests/eval/queries.yaml --impact-queries tests/eval/impact_queries.yaml`.
2. **Accept and refresh the baseline**. Only when the regression is
   *intentional* (e.g. you deliberately traded recall for precision, or
   removed a tuning hack). See below.

## Refreshing the baseline

Manual, label-gated. The workflow has a `workflow_dispatch` entry point
with a `refresh_baseline=true` input. From the PR branch:

```
gh workflow run eval.yml -f refresh_baseline=true --ref <pr-branch>
```

The `baseline-refresh` job will:

1. Index the fixture.
2. Capture a fresh `EvalReport` via the production retriever.
3. Commit `tests/eval/baselines/main.json` back to the branch with message
   `chore(eval): refresh baseline via workflow_dispatch`.

Because the refresh is a separate run of a separate job, the regression
gate does **not** re-trigger automatically. The next push to the PR will
run it against the new baseline (passing this time).

## Secrets

The core promptfoo gate does **not** require `ANTHROPIC_API_KEY` — it
asserts IR metrics only. The RAGAS LLM-judge path (`make eval-full`) is
manual/local for now and deliberately not in CI.

If/when LLM-judge metrics move into CI, add `ANTHROPIC_API_KEY` as a repo
secret under *Settings → Secrets and variables → Actions* and reference
it as `${{ secrets.ANTHROPIC_API_KEY }}` in the workflow.

## Cross-reference

- Workflow: [`.github/workflows/eval.yml`](../../.github/workflows/eval.yml)
- Config: [`tests/eval/promptfoo.config.yaml`](../../tests/eval/promptfoo.config.yaml)
- Baseline: [`tests/eval/baselines/main.json`](../../tests/eval/baselines/main.json)
- Spec: [`specs/006-ragas-promptfoo-eval/spec.md`](../../specs/006-ragas-promptfoo-eval/spec.md)
  (US2, SC-004, SC-006)
