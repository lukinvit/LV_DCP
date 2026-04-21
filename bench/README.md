# devctx-bench

Retrieval-only benchmark harness for code-context tools.

Most AI-coding benchmarks (SWE-Bench, RepoBench) score end-to-end agentic
performance, where model choice dominates the signal. `devctx-bench`
isolates the *retrieval* layer: given a query set with ground truth,
compute recall@k, precision@k, MRR, and impact_recall@5 against any
retriever callable.

## Install

```bash
pip install devctx-bench
```

## Quick start

### 1. Write a queries file

See [`examples/queries.yaml`](./examples/queries.yaml):

```yaml
queries:
  - id: q01
    text: "session token refresh"
    mode: navigate
    expected:
      files:
        - "src/auth/session.py"
```

### 2. Plug in your retriever

Any callable matching `(query: str, mode: str, repo: Path) -> (files: list[str], symbols: list[str])`:

```python
# file: my_retriever.py
from pathlib import Path


def retrieve(query: str, mode: str, repo: Path) -> tuple[list[str], list[str]]:
    # ... your retrieval logic ...
    return (["src/auth/session.py"], ["src.auth.session.refresh"])
```

### 3. Run the benchmark

```bash
devctx-bench run /path/to/your/repo \
    --queries queries.yaml \
    --retriever-module my_retriever:retrieve
```

Output is a markdown report with recall@5, precision@3, MRR, impact_recall@5,
and a per-query breakdown showing which expected files were missed.

## Python API

```python
from pathlib import Path

from devctx_bench import load_queries_file, run_eval, generate_per_query_report


def my_retriever(query, mode, repo):
    return ["src/auth/session.py"], []


queries = load_queries_file(Path("queries.yaml"))
report = run_eval(
    my_retriever,
    repo_path=Path("./my-repo"),
    navigate_queries=queries,
)
print(generate_per_query_report(report, tag="my-retriever"))
```

## Metrics

| Metric | Meaning |
|---|---|
| `recall@5` | Fraction of expected files that appear in the top 5 retrieved. |
| `precision@3` | Fraction of top 3 retrieved that are in the expected set. |
| `MRR` (files) | Mean reciprocal rank of the first expected hit. |
| `recall@5_symbols` | Recall over expected symbol fq_names. |
| `impact_recall@5` | Recall@5 computed only over graph-expansion (edit-mode) queries. Separated so retrieval strategies that optimize one side of that divide don't mask regressions on the other. |

All metrics are defined in [`devctx_bench/metrics.py`](./src/devctx_bench/metrics.py)
as pure functions — zero I/O, zero state.

## Comparing retrievers (baselines)

Because `run_eval` is retriever-agnostic, you can run any number of retrievers
against the same query set and diff the reports. `devctx_bench.report`
ships `generate_comparison_report(primary, baseline)` for a side-by-side
markdown table.

The sister package [`lv-dcp`](https://github.com/lukinvit/LV_DCP) ships an
Aider-style PageRank repo-map baseline you can use as a comparator. Its
source lives in `lv-dcp`'s `tests/eval/baselines/aider_repomap.py`.

## Design notes

- **Pure Python, no ML stack**: `devctx-bench` has three runtime dependencies
  (`pyyaml`, `typer`, `rich`). It does not bring tree-sitter, Qdrant, or
  embedding models — those are concerns of the *retriever* you plug in.
- **Deterministic metrics**: no randomness; re-running the same retriever
  on the same query set produces identical reports.
- **Empty-ground-truth safety**: `recall_at_k([], [])` returns 1.0 — a
  query with no expected items cannot miss.
- **Layering**: `metrics` → `runner` → `report`. `loader` is stateless.
  `cli` imports everything.

## License

Apache-2.0.
