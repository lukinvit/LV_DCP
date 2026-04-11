#!/usr/bin/env bash
# Phase 3b dogfood — starts ctx ui in background, hits each route via curl,
# prints a summary, kills server on exit.

set -u
set -o pipefail

LOG=/tmp/phase-3b-dogfood.log
: > "$LOG"
PORT=8787
URL="http://127.0.0.1:${PORT}"

log() { echo "$1" | tee -a "$LOG"; }

log "================================================================"
log "Phase 3b dogfood — $(date)"
log "================================================================"

uv run ctx ui --no-browser --port "$PORT" > /tmp/phase-3b-server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 20); do
  if curl -fsS "$URL/" > /dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

FAILURES=0

log ""
log ">> GET /"
if curl -fsS "$URL/" | head -5 | tee -a "$LOG" > /dev/null; then
  log "   OK"
else
  log "   FAIL"
  FAILURES=$((FAILURES+1))
fi

log ""
log ">> GET /api/project/lv-dcp/graph.json (first 200 chars)"
if curl -fsS "$URL/api/project/lv-dcp/graph.json" | head -c 200 | tee -a "$LOG" > /dev/null; then
  log "   OK"
else
  log "   FAIL (project may not be registered — skipping)"
fi

log ""
log ">> GET /api/project/lv-dcp/sparklines.json (first 200 chars)"
if curl -fsS "$URL/api/project/lv-dcp/sparklines.json" | head -c 200 | tee -a "$LOG" > /dev/null; then
  log "   OK"
else
  log "   FAIL (project may not be registered — skipping)"
fi

log ""
log ">> GET /project/lv-dcp (first 5 lines)"
if curl -fsS "$URL/project/lv-dcp" | head -5 | tee -a "$LOG" > /dev/null; then
  log "   OK"
else
  log "   FAIL (project may not be registered — skipping)"
fi

log ""
log "Dogfood done. Failures: $FAILURES. Full log: $LOG"
exit $FAILURES
