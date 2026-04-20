# Aider repo-map baseline vs LV_DCP pipeline (2026-04-21)

Aider's PageRank-over-tree-sitter-tags repo-map is the closest OSS analog
to LV_DCP's retrieval layer (see `aider.chat/2023/10/22/repomap.html`).
This report benchmarks an emulation of that baseline against the full
LV_DCP pipeline on the synthetic `sample_repo` fixture (32 queries: 20
navigate + 12 impact).

## Results

| Metric | LV_DCP | Aider baseline | Delta |
|---|---|---|---|
| recall@5 files | 0.9635 | 0.5755 | **+0.388 (+67% rel)** |
| precision@3 files | 0.6979 | 0.2917 | **+0.406 (+139% rel)** |
| recall@5 symbols | 0.8958 | 0.1562 | **+0.740 (+474% rel)** |
| MRR files | 0.9688 | 0.7126 | **+0.256 (+36% rel)** |
| impact_recall@5 | 0.9306 | 0.5208 | **+0.410 (+79% rel)** |

LV_DCP's multi-stage pipeline (FTS + symbol match + role weights + graph
expansion + path-token boost + **centrality boost (this release)**)
dominates personalized-PageRank ranking on every metric.

## Methodology

- Both retrievers run against **the same** sample_repo fixture with
  identical queries.
- Both retrievers use **LV_DCP's graph and parsing output** — this isolates
  the ranking algorithm from parsing quality.
- Aider baseline personalization: overlap between query identifier tokens
  and each file's path tokens, fed as the PageRank teleport vector.
- Baseline code: `tests/eval/baselines/aider_repomap.py`.

## Why the gap

Aider's repo-map shines in its **intended setting**: a one-shot outline
presented to the LLM with a ~1k-token budget. Ranking is the last mile of
a bigger agentic flow.

The synthetic eval measures pure retrieval recall/precision, where
LV_DCP's layered signals give it a large edge:

1. **FTS5 over identifier-tokenized corpus** catches exact-name hits
   PageRank cannot see.
2. **Role weights** demote docs/tests in navigate mode — Aider ranks them
   just like code.
3. **Graph expansion** adds impacted files for edit queries — Aider's
   single-pass PageRank does not diffuse from query seeds.
4. **Path-token boost** (Phase 7c) rewards filename-identifier overlap
   beyond what personalization alone captures.

## Caveats

- The baseline does not implement Aider's token-budgeted **outline**
  rendering — it only compares ranking. Aider's context-pack quality in
  real usage depends on both ranking and outline fidelity; this eval
  isolates the first half.
- Aider derives personalization from chat history (files the user named).
  The synthetic harness has no chat, so the baseline proxies with query
  tokens — a fair approximation but not identical to the live product.
- sample_repo is 23 files. At scale (>10k files) PageRank's signal/noise
  ratio improves; the gap may narrow. Phase 3 cross-project eval will
  revisit this on real large repos.

## Reproduce

```bash
uv run python - <<'PY'
from tests.eval.baselines.aider_repomap import aider_baseline_retrieve
from tests.eval.retrieval_adapter import retrieve_for_eval
from tests.eval.run_eval import run_eval

print(run_eval(retrieve_for_eval))
print(run_eval(aider_baseline_retrieve))
PY
```

## Implications for the roadmap

- **Keep the multi-stage pipeline.** The ablation data argue strongly
  against simplifying retrieval down to "just PageRank."
- **Ship Aider baseline in the harness** — future PRs can detect
  accidental regressions toward baseline ranking.
- **Cross-project PageRank stays on the watch list.** The baseline is
  weakest on recall@5_symbols (0.156); any move toward Aider-style
  identifier outlines in LV_DCP's pack layer must preserve our
  multi-signal ranking.
