#!/usr/bin/env bash
# LV_DCP git post-merge hook — spec-010 T035.
#
# Fires after `git merge` (and `git pull`, which calls merge). We:
#   1. Kick off `ctx scan` so symbols from merged commits are captured.
#   2. If a MERGE_MSG reference indicates history was rewritten (squash),
#      run `ctx timeline reconcile` afterward to flag orphaned commits.
#
# Detached + best-effort; never blocks the merge.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
    exit 0
fi

LOG_DIR="${REPO_ROOT}/.context/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/timeline-hook.log"

SQUASH_FLAG="${1:-0}"  # git passes "1" when this was a squash merge

(
    cd "${REPO_ROOT}"
    if ! command -v ctx >/dev/null 2>&1; then
        echo "[$(date -Is)] post-merge: ctx CLI not on PATH — skipped" >>"${LOG_FILE}"
        exit 0
    fi
    echo "[$(date -Is)] post-merge: ctx scan ${REPO_ROOT}" >>"${LOG_FILE}"
    ctx scan "${REPO_ROOT}" >>"${LOG_FILE}" 2>&1 || \
        echo "[$(date -Is)] post-merge: scan failed" >>"${LOG_FILE}"

    if [[ "${SQUASH_FLAG}" == "1" ]]; then
        echo "[$(date -Is)] post-merge: squash merge → reconcile" >>"${LOG_FILE}"
        ctx timeline reconcile --project "${REPO_ROOT}" >>"${LOG_FILE}" 2>&1 || \
            echo "[$(date -Is)] post-merge: reconcile failed" >>"${LOG_FILE}"
    fi
) >/dev/null 2>&1 &
disown
