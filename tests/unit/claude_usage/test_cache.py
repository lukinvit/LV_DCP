from __future__ import annotations

import json
from pathlib import Path

from libs.claude_usage.cache import UsageCache


def _assistant(ts: str, i: int = 10, o: int = 5) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "s1",
        "message": {
            "usage": {
                "input_tokens": i,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": o,
            }
        },
    }


def _make_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_first_scan_reads_full_file(tmp_path: Path) -> None:
    session_file = tmp_path / "sess.jsonl"
    _make_jsonl(session_file, [_assistant("2026-04-11T10:00:00Z", i=100, o=50)])

    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    events = cache.sync_and_query(session_file, since_ts=0.0)
    assert len(events) == 1
    assert events[0].input_tokens == 100


def test_incremental_scan_reads_only_new_lines(tmp_path: Path) -> None:
    session_file = tmp_path / "sess.jsonl"
    _make_jsonl(session_file, [_assistant("2026-04-11T10:00:00Z", i=100)])

    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    cache.sync_and_query(session_file, since_ts=0.0)

    with session_file.open("a") as fh:
        fh.write(json.dumps(_assistant("2026-04-11T11:00:00Z", i=200)) + "\n")

    events = cache.sync_and_query(session_file, since_ts=0.0)
    input_total = sum(e.input_tokens for e in events)
    assert input_total == 300


def test_since_ts_filters_results(tmp_path: Path) -> None:
    session_file = tmp_path / "sess.jsonl"
    _make_jsonl(
        session_file,
        [
            _assistant("2026-04-11T10:00:00Z", i=100),
            _assistant("2026-04-11T12:00:00Z", i=200),
        ],
    )
    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    from datetime import datetime

    mid = datetime.fromisoformat("2026-04-11T11:00:00+00:00").timestamp()

    events = cache.sync_and_query(session_file, since_ts=mid)
    assert len(events) == 1
    assert events[0].input_tokens == 200


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    missing = tmp_path / "nonexistent.jsonl"
    events = cache.sync_and_query(missing, since_ts=0.0)
    assert events == []
