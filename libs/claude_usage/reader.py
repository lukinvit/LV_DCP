"""Parse ~/.claude/projects/<encoded>/*.jsonl session files and yield UsageEvent rows."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class UsageEvent:
    timestamp_unix: float
    session_id: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int


def _parse_iso(ts: str) -> float:
    """Parse ISO 8601 timestamp to unix seconds. Accepts 'Z' suffix."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


def read_session_file(
    path: Path,
    *,
    start_offset: int = 0,
) -> Iterator[UsageEvent]:
    """Yield a UsageEvent for every `type=assistant` record in the JSONL file.

    Malformed lines and records without `message.usage` are silently skipped.
    `start_offset` is a byte offset into the file, useful for incremental reads.
    """
    try:
        with path.open("rb") as fh:
            if start_offset:
                fh.seek(start_offset)
            for raw in fh:
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(usage, dict):
                    continue
                yield UsageEvent(
                    timestamp_unix=_parse_iso(str(obj.get("timestamp", ""))),
                    session_id=str(obj.get("sessionId", "")),
                    input_tokens=int(usage.get("input_tokens", 0) or 0),
                    cache_creation_input_tokens=int(
                        usage.get("cache_creation_input_tokens", 0) or 0
                    ),
                    cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
                    output_tokens=int(usage.get("output_tokens", 0) or 0),
                )
    except (OSError, PermissionError):
        return
