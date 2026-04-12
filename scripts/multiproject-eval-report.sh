#!/usr/bin/env bash
# scripts/multiproject-eval-report.sh <tag>
# Runs multi-project eval and writes a report.
set -euo pipefail

tag="${1:-phase4-week1}"
date_str=$(date +%Y-%m-%d)
output="docs/eval/${date_str}-multiproject-${tag}.md"

uv run python -c "
from pathlib import Path
import yaml
import sys

fixture = yaml.safe_load(Path('tests/eval/multiproject_queries.yaml').read_text())
config_path = Path.home() / '.lvdcp' / 'config.yaml'
if not config_path.exists():
    print('ERROR: no config.yaml found')
    sys.exit(1)

config = yaml.safe_load(config_path.read_text())
roots = {Path(p['root']).name: Path(p['root']) for p in config.get('projects', [])}

from libs.project_index.index import ProjectIndex
from libs.scanning.scanner import scan_project

lines = ['# Multi-project Eval \u2014 ${tag}', '', '## Per-project results', '']
total_recall = []

for proj_name, proj_data in fixture.get('projects', {}).items():
    root = roots.get(proj_name)
    if root is None or not root.exists():
        lines.append(f'### {proj_name} \u2014 SKIPPED (not registered)')
        lines.append('')
        continue
    try:
        scan_project(root, mode='incremental')
        idx = ProjectIndex.open(root)
    except Exception as e:
        lines.append(f'### {proj_name} \u2014 ERROR: {e}')
        lines.append('')
        continue

    lines.append(f'### {proj_name}')
    lines.append('')
    lines.append('| id | recall@5 | missed |')
    lines.append('|---|---|---|')

    proj_recalls = []
    for q in proj_data.get('queries', []):
        result = idx.retrieve(q['text'], mode=q['mode'], limit=10)
        expected = set(q.get('expected', {}).get('files', []))
        found = set(result.files[:5])
        hits = expected & found
        missed = expected - found
        recall = len(hits) / len(expected) if expected else 1.0
        proj_recalls.append(recall)
        total_recall.append(recall)
        missed_str = ', '.join(sorted(missed)) if missed else chr(8212)
        lines.append(f'| {q[\"id\"]} | {recall:.2f} | {missed_str} |')

    avg = sum(proj_recalls) / len(proj_recalls) if proj_recalls else 0.0
    lines.append('')
    lines.append(f'**Average recall@5: {avg:.3f}**')
    lines.append('')
    idx.close()

global_avg = sum(total_recall) / len(total_recall) if total_recall else 0.0
lines.append(f'## Global average recall@5: {global_avg:.3f}')
lines.append('')

out = Path('${output}')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text('\n'.join(lines))
print(f'Wrote {out}')
print(f'Global recall@5: {global_avg:.3f}')
"
