"""Git intelligence data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GitFileStats:
    file_path: str
    commit_count: int = 0
    churn_30d: int = 0
    last_modified_ts: float = 0.0
    age_days: int = 0
    authors: list[str] = field(default_factory=list)
    primary_author: str = ""
    last_author: str = ""
