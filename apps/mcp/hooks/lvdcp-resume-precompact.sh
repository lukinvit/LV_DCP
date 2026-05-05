#!/usr/bin/env bash
set -e
exec timeout 5 ctx breadcrumb capture --source=hook_pre_compact --summary-from-stdin 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
