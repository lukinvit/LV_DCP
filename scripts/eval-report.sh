#!/usr/bin/env bash
# scripts/eval-report.sh <tag> [repo_path]
# Runs eval harness and writes a timestamped per-query Markdown report.
set -euo pipefail

tag="${1:-baseline}"
repo_path="${2:-}"
date_str=$(date +%Y-%m-%d)
output="docs/eval/${date_str}-${tag}.md"

uv run python -c "
from pathlib import Path
from tests.eval.run_eval import run_eval, generate_per_query_report
from tests.eval.retrieval_adapter import retrieve_for_eval
repo = Path('${repo_path}') if '${repo_path}' else None
kwargs = {'repo_path': repo} if repo else {}
report = run_eval(retrieve_for_eval, **kwargs)
md = generate_per_query_report(report, tag='${tag}')
out = Path('${output}')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(md)
print(f'Wrote {out}')
print(f'  recall@5 files:  {report.recall_at_5_files:.3f}')
print(f'  precision@3:     {report.precision_at_3_files:.3f}')
print(f'  impact_recall@5: {report.impact_recall_at_5:.3f}')
"
