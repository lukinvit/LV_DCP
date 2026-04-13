#!/usr/bin/env bash
# scripts/polyglot-eval-report.sh <tag>
# Runs advisory polyglot eval and writes a markdown report.
set -euo pipefail

tag="${1:-manual}"
uv run python scripts/real_project_eval_report.py polyglot "${tag}"
