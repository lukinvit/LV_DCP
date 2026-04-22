#!/usr/bin/env bash
# LV_DCP git post-rewrite hook — spec-010 T035.
#
# Fires after `git commit --amend` and `git rebase`. Both rewrite commit
# SHAs, which means timeline events still point at now-unreachable
# commits. We run `ctx timeline reconcile` to flag them as orphaned.
#
# Followed by a fresh `ctx scan` so the new commit graph is reflected.
# Both steps are best-effort and detached.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
    exit 0
fi

LOG_DIR="${REPO_ROOT}/.context/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/timeline-hook.log"

REASON="${1:-unknown}"  # amend | rebase

(
    cd "${REPO_ROOT}"
    if ! command -v ctx >/dev/null 2>&1; then
        echo "[$(date -Is)] post-rewrite(${REASON}): ctx CLI not on PATH — skipped" \
            >>"${LOG_FILE}"
        exit 0
    fi
    echo "[$(date -Is)] post-rewrite(${REASON}): reconcile + scan" >>"${LOG_FILE}"
    ctx timeline reconcile --project "${REPO_ROOT}" >>"${LOG_FILE}" 2>&1 || \
        echo "[$(date -Is)] post-rewrite: reconcile failed" >>"${LOG_FILE}"
    ctx scan "${REPO_ROOT}" >>"${LOG_FILE}" 2>&1 || \
        echo "[$(date -Is)] post-rewrite: scan failed" >>"${LOG_FILE}"
) >/dev/null 2>&1 &
disown
