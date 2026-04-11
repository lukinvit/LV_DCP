from __future__ import annotations

import json
from pathlib import Path

from libs.claude_usage.aggregator import TokenTotals, UsageAggregator
from libs.claude_usage.cache import UsageCache


def _assistant(ts_iso: str, i: int = 10, c_create: int = 0, c_read: int = 0, o: int = 5) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts_iso,
        "sessionId": "s1",
        "message": {
            "usage": {
                "input_tokens": i,
                "cache_creation_input_tokens": c_create,
                "cache_read_input_tokens": c_read,
                "output_tokens": o,
            }
        },
    }


def test_rolling_window_sums_tokens_from_multiple_sessions(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    encoded_dir = projects_dir / "-abs-proj"
    encoded_dir.mkdir(parents=True)
    s1 = encoded_dir / "s1.jsonl"
    s2 = encoded_dir / "s2.jsonl"
    s1.write_text(json.dumps(_assistant("2026-04-11T10:00:00Z", i=100, o=50)) + "\n")
    s2.write_text(json.dumps(_assistant("2026-04-11T11:00:00Z", i=200, o=80)) + "\n")

    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    aggregator = UsageAggregator(cache, projects_dir=projects_dir)

    totals = aggregator.rolling_window(project_encoded_name="-abs-proj", since_ts=0.0)
    assert isinstance(totals, TokenTotals)
    assert totals.input_tokens == 300
    assert totals.output_tokens == 130


def test_rolling_window_returns_zero_for_unknown_project(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    agg = UsageAggregator(cache, projects_dir=projects_dir)
    totals = agg.rolling_window("-nowhere", since_ts=0)
    assert totals == TokenTotals(0, 0, 0, 0)


def test_global_rolling_window_sums_across_all_projects(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    (projects_dir / "-a").mkdir(parents=True)
    (projects_dir / "-b").mkdir(parents=True)
    (projects_dir / "-a" / "s.jsonl").write_text(
        json.dumps(_assistant("2026-04-11T10:00:00Z", i=100)) + "\n"
    )
    (projects_dir / "-b" / "s.jsonl").write_text(
        json.dumps(_assistant("2026-04-11T10:00:00Z", i=200)) + "\n"
    )

    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    agg = UsageAggregator(cache, projects_dir=projects_dir)

    totals = agg.global_rolling_window(since_ts=0.0)
    assert totals.input_tokens == 300


def test_global_rolling_window_empty_projects_dir(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    cache = UsageCache(tmp_path / "cache.db")
    cache.migrate()
    agg = UsageAggregator(cache, projects_dir=projects_dir)
    totals = agg.global_rolling_window(since_ts=0.0)
    assert totals == TokenTotals(0, 0, 0, 0)
