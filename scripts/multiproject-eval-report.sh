#!/usr/bin/env bash
# scripts/multiproject-eval-report.sh <tag>
# Runs advisory multi-project eval and writes a markdown report.
set -euo pipefail

tag="${1:-manual}"
uv run python scripts/real_project_eval_report.py multiproject "${tag}"
