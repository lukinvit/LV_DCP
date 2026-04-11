#!/usr/bin/env bash
# Phase 3c.1 dogfood — enables LLM, runs ctx summarize on LV_DCP canary + 2
# sibling projects, records cost + cache hit rate.
#
# Requires: OPENAI_API_KEY env var set.
# Usage: scripts/phase-3c1-dogfood.sh

set -u
set -o pipefail

LOG=/tmp/phase-3c1-dogfood.log
: > "$LOG"

log() { echo "$1" | tee -a "$LOG"; }

log "================================================================"
log "Phase 3c.1 dogfood — $(date)"
log "================================================================"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    log "ERROR: OPENAI_API_KEY not set. Run: export OPENAI_API_KEY=sk-..."
    exit 1
fi

log ""
log ">> Enabling LLM in ~/.lvdcp/config.yaml"
uv run python -c "
import yaml
from pathlib import Path
p = Path.home() / '.lvdcp' / 'config.yaml'
data = yaml.safe_load(p.read_text()) if p.exists() else {'version': 1, 'projects': []}
if data is None:
    data = {'version': 1, 'projects': []}
data.setdefault('llm', {})
data['llm']['provider'] = 'openai'
data['llm']['summary_model'] = 'gpt-4o-mini'
data['llm']['enabled'] = True
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(yaml.safe_dump(data, sort_keys=False))
print('enabled')
" | tee -a "$LOG"

PROJECTS=(
    "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP"
    "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_Proxy_enaibler_bot"
    "/Users/v.lukin/Nextcloud/lukinvit.tech/projects/TG_RUSCOFFEE_ADMIN_BOT"
)

for PROJECT in "${PROJECTS[@]}"; do
    log ""
    log "================================================================"
    log "Project: $PROJECT"
    log "================================================================"

    if [[ ! -d "$PROJECT" ]]; then
        log "   SKIP (directory missing)"
        continue
    fi

    log ">> ctx summarize $PROJECT"
    uv run ctx summarize "$PROJECT" 2>&1 | tee -a "$LOG"
done

log ""
log ">> ctx mcp doctor (should show 9 checks including LLM provider + budget)"
uv run ctx mcp doctor 2>&1 | tee -a "$LOG"

log ""
log "Dogfood done. Full log: $LOG"
