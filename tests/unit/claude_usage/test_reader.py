from __future__ import annotations

import json
from pathlib import Path

from libs.claude_usage.reader import UsageEvent, read_session_file  # noqa: F401


def _assistant_record(ts: str, input_tokens: int = 10, output_tokens: int = 5) -> dict[str, object]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "sess-1",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 50,
                "output_tokens": output_tokens,
            }
        },
    }


def _user_record(ts: str) -> dict[str, object]:
    return {"type": "user", "timestamp": ts, "sessionId": "sess-1"}


def test_read_session_file_extracts_assistant_usage(tmp_path: Path) -> None:
    f = tmp_path / "session.jsonl"
    records = [
        _user_record("2026-04-11T10:00:00Z"),
        _assistant_record("2026-04-11T10:00:01Z", input_tokens=200, output_tokens=80),
        _assistant_record("2026-04-11T10:00:05Z", input_tokens=50, output_tokens=20),
    ]
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    events = list(read_session_file(f))
    assert len(events) == 2
    assert events[0].input_tokens == 200
    assert events[0].output_tokens == 80
    assert events[0].cache_creation_input_tokens == 100
    assert events[0].cache_read_input_tokens == 50
    assert events[1].input_tokens == 50


def test_read_session_file_skips_malformed_lines(tmp_path: Path) -> None:
    f = tmp_path / "session.jsonl"
    f.write_text(
        "\n".join(
            [
                "not json",
                json.dumps(_user_record("2026-04-11T10:00:00Z")),
                json.dumps(_assistant_record("2026-04-11T10:00:01Z")),
                "",
                '{"incomplete',
            ]
        )
        + "\n"
    )
    events = list(read_session_file(f))
    assert len(events) == 1


def test_read_session_file_handles_missing_usage_field(tmp_path: Path) -> None:
    f = tmp_path / "session.jsonl"
    assistant_no_usage = {
        "type": "assistant",
        "timestamp": "2026-04-11T10:00:00Z",
        "sessionId": "s",
        "message": {},
    }
    f.write_text(json.dumps(assistant_no_usage) + "\n")
    events = list(read_session_file(f))
    assert events == []


def test_read_session_file_with_byte_offset(tmp_path: Path) -> None:
    f = tmp_path / "session.jsonl"
    line1 = json.dumps(_assistant_record("2026-04-11T10:00:00Z", input_tokens=100)) + "\n"
    line2 = json.dumps(_assistant_record("2026-04-11T10:00:01Z", input_tokens=200)) + "\n"
    f.write_text(line1 + line2)

    offset = len(line1.encode("utf-8"))
    events = list(read_session_file(f, start_offset=offset))
    assert len(events) == 1
    assert events[0].input_tokens == 200
