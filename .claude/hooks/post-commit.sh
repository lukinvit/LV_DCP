#!/usr/bin/env bash
# LV_DCP git post-commit hook — spec-010 T035.
#
# Runs after every `git commit` in the repo. We kick off an incremental
# `ctx scan` so the new commit's symbol changes land in
# symbol_timeline_events with the correct commit_sha.
#
# The scan is best-effort and runs detached: a slow scan must NEVER block
# the user's commit. Output goes to .context/logs/timeline-hook.log.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
    exit 0  # not in a git repo — nothing to do
fi

LOG_DIR="${REPO_ROOT}/.context/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/timeline-hook.log"

# Detached background scan; the commit returns instantly.
(
    cd "${REPO_ROOT}"
    if command -v ctx >/dev/null 2>&1; then
        echo "[$(date -Is)] post-commit: ctx scan ${REPO_ROOT}" >>"${LOG_FILE}"
        ctx scan "${REPO_ROOT}" >>"${LOG_FILE}" 2>&1 || \
            echo "[$(date -Is)] post-commit: scan failed" >>"${LOG_FILE}"
    else
        echo "[$(date -Is)] post-commit: ctx CLI not on PATH — skipped" >>"${LOG_FILE}"
    fi
) >/dev/null 2>&1 &
disown
