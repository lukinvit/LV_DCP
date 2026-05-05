#!/usr/bin/env bash
set -e
mkdir -p "$HOME/Library/Logs/lvdcp"
exec timeout 5 ctx resume --inject --quiet 2>>"$HOME/Library/Logs/lvdcp/hook.log" || true
