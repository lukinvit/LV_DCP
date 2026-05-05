#!/usr/bin/env bash
set -e
exec timeout 5 ctx breadcrumb capture --source=hook_subagent_stop 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
