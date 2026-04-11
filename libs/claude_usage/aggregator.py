"""Aggregation over UsageCache — sums tokens per project or globally for a time window."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from libs.claude_usage.cache import UsageCache

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class TokenTotals:
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int

    def __add__(self, other: TokenTotals) -> TokenTotals:
        return TokenTotals(
            self.input_tokens + other.input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.output_tokens + other.output_tokens,
        )


class UsageAggregator:
    def __init__(
        self,
        cache: UsageCache,
        *,
        projects_dir: Path = DEFAULT_PROJECTS_DIR,
    ) -> None:
        self._cache = cache
        self._projects_dir = projects_dir

    def rolling_window(
        self,
        project_encoded_name: str,
        *,
        since_ts: float,
    ) -> TokenTotals:
        """Return per-project TokenTotals across all session files >= since_ts."""
        project_path = self._projects_dir / project_encoded_name
        if not project_path.exists() or not project_path.is_dir():
            return TokenTotals(0, 0, 0, 0)
        totals = TokenTotals(0, 0, 0, 0)
        for session_file in project_path.glob("*.jsonl"):
            events = self._cache.sync_and_query(session_file, since_ts=since_ts)
            for ev in events:
                totals = totals + TokenTotals(
                    ev.input_tokens,
                    ev.cache_creation_input_tokens,
                    ev.cache_read_input_tokens,
                    ev.output_tokens,
                )
        return totals

    def global_rolling_window(self, *, since_ts: float) -> TokenTotals:
        """Sum token usage across every project directory under projects_dir."""
        if not self._projects_dir.exists():
            return TokenTotals(0, 0, 0, 0)
        totals = TokenTotals(0, 0, 0, 0)
        for project_dir in self._projects_dir.iterdir():
            if project_dir.is_dir():
                totals = totals + self.rolling_window(project_dir.name, since_ts=since_ts)
        return totals
