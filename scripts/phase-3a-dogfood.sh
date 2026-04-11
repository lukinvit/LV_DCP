#!/usr/bin/env bash
# Phase 3a dogfood — runs the 7-step exit criterion on each project.
#
# Usage: scripts/phase-3a-dogfood.sh
#
# Projects exercised:
#   - /Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP
#   - /Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_Proxy_enaibler_bot
#   - /Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_RUSCOFFEE_ADMIN_BOT
#
# Outputs status per project. Non-zero exit code = at least one step failed.

set -u

PROJECTS=(
  "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP"
  "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_Proxy_enaibler_bot"
  "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_RUSCOFFEE_ADMIN_BOT"
)

FAIL_COUNT=0
LOG_FILE="${LVDCP_DOGFOOD_LOG:-/tmp/phase-3a-dogfood.log}"
: > "$LOG_FILE"

log() {
  echo "$1" | tee -a "$LOG_FILE"
}

run_step() {
  local label="$1"
  shift
  log ">> $label"
  if "$@" 2>&1 | tee -a "$LOG_FILE"; then
    log "   OK"
    return 0
  else
    log "   FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    return 1
  fi
}

for PROJECT in "${PROJECTS[@]}"; do
  log ""
  log "================================================================"
  log "Project: $PROJECT"
  log "================================================================"

  if [[ ! -d "$PROJECT" ]]; then
    log "   SKIP (directory missing)"
    continue
  fi

  run_step "ctx mcp install" uv run ctx mcp install

  run_step "ctx mcp doctor" uv run ctx mcp doctor

  run_step "ctx scan $PROJECT" uv run ctx scan "$PROJECT"

  log ">> ctx watch install-service (may fail in headless session)"
  if uv run ctx watch install-service 2>&1 | tee -a "$LOG_FILE"; then
    log "   OK"
    uv run ctx watch uninstall-service 2>&1 | tee -a "$LOG_FILE" || true
  else
    log "   SKIP (headless or already loaded)"
  fi

  run_step "mcp handshake via doctor --json" bash -c \
    'uv run ctx mcp doctor --json | python -c "import json,sys; r=json.load(sys.stdin); h=[c for c in r[\"checks\"] if c[\"name\"]==\"mcp handshake\"]; exit(0 if h and h[0][\"status\"]==\"PASS\" else 1)"'

  run_step "ctx mcp uninstall" uv run ctx mcp uninstall

  uv run ctx mcp install 2>&1 >/dev/null || true
done

log ""
log "================================================================"
log "Total failures: $FAIL_COUNT"
log "Full log: $LOG_FILE"
log "================================================================"

exit $FAIL_COUNT
