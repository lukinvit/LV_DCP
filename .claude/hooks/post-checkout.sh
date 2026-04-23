#!/usr/bin/env bash
# LV_DCP git post-checkout hook — spec-010 T035.
#
# Fires on `git checkout`, `git switch`, and the first `git clone`. By
# design this is a NO-OP on the timeline: switching branches doesn't
# rewrite history, it just moves the working tree. A new scan would only
# produce noise — the existing events already describe the symbols we
# just checked out.
#
# We write a single breadcrumb to the log for operator visibility and
# exit.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
    exit 0
fi

LOG_DIR="${REPO_ROOT}/.context/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/timeline-hook.log"

# Args: prev_HEAD new_HEAD is_branch_checkout
HEAD_NOW="${2:-unknown}"
echo "[$(date -Is)] post-checkout: HEAD=${HEAD_NOW} — timeline no-op" >>"${LOG_FILE}"
