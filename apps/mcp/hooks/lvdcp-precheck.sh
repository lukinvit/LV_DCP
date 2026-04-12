#!/usr/bin/env bash
# LV_DCP pre-tool hook: reminds Claude to use lvdcp_pack before Grep/Read
# Checks if the project has .context/cache.db (is indexed by LV_DCP)
# If yes, injects a system reminder to call lvdcp_pack first.

set -euo pipefail

# Read tool input from stdin
INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only trigger for Grep and Read
case "$TOOL_NAME" in
  Grep|Read) ;;
  *) exit 0 ;;
esac

# Extract the file/path being accessed
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.path // .tool_input.file_path // empty')
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Find project root (walk up to find .context/cache.db)
DIR="$FILE_PATH"
if [ -f "$DIR" ]; then
  DIR=$(dirname "$DIR")
fi

FOUND_CACHE=""
CHECK_DIR="$DIR"
for i in $(seq 1 10); do
  if [ -f "$CHECK_DIR/.context/cache.db" ]; then
    FOUND_CACHE="$CHECK_DIR"
    break
  fi
  PARENT=$(dirname "$CHECK_DIR")
  if [ "$PARENT" = "$CHECK_DIR" ]; then
    break
  fi
  CHECK_DIR="$PARENT"
done

if [ -z "$FOUND_CACHE" ]; then
  exit 0
fi

# Project is indexed — remind about lvdcp_pack
cat << HOOKEOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "REMINDER: This project ($FOUND_CACHE) is indexed by LV_DCP. Consider calling lvdcp_pack(path=\"$FOUND_CACHE\", query=\"<your question>\") first — it returns ranked relevant files in 2-20 KB instead of grep-walking the repo."
  }
}
HOOKEOF
