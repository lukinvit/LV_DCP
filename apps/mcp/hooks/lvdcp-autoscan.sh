#!/usr/bin/env bash
# LV_DCP post-tool hook: incremental rescan after file changes
# Triggers on Write/Edit — updates .context/cache.db for the changed file only.
# Runs async so it doesn't block Claude.

set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Get the file path from tool response or input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Find project root with .context/cache.db
DIR=$(dirname "$FILE_PATH")
FOUND=""
CHECK_DIR="$DIR"
for i in $(seq 1 10); do
  if [ -f "$CHECK_DIR/.context/cache.db" ]; then
    FOUND="$CHECK_DIR"
    break
  fi
  PARENT=$(dirname "$CHECK_DIR")
  if [ "$PARENT" = "$CHECK_DIR" ]; then break; fi
  CHECK_DIR="$PARENT"
done

if [ -z "$FOUND" ]; then
  exit 0
fi

# Get relative path
REL_PATH="${FILE_PATH#$FOUND/}"

# Incremental scan for just this file (fast, <1s)
cd "$FOUND"
python3 -c "
from pathlib import Path
from libs.scanning.scanner import scan_project
scan_project(Path('.'), mode='incremental', only={'$REL_PATH'})
" 2>/dev/null || true
