"""Batch git log extraction --- one subprocess call per project, not per file."""

from __future__ import annotations

import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from libs.gitintel.models import GitFileStats


def extract_git_stats(root: Path, *, timeout: int = 30) -> dict[str, GitFileStats]:
    """Extract per-file git stats from a single batch ``git log`` call.

    Returns a mapping of relative file paths to their ``GitFileStats``.
    Returns an empty dict for non-git directories or on any git error.
    """
    if not (root / ".git").is_dir():
        return {}

    now = time.time()
    thirty_days_ago = now - 30 * 86400

    try:
        result = subprocess.run(
            ["git", "log", "--format=%H|%aI|%aN", "--name-only"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return {}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    # Parse git log output: commit header lines contain '|', file lines don't.
    file_commits: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    current_commit: tuple[str, float, str] | None = None

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line and line.count("|") == 2:
            parts = line.split("|", 2)
            try:
                ts = datetime.fromisoformat(parts[1]).replace(tzinfo=UTC).timestamp()
            except (ValueError, IndexError):
                ts = 0.0
            current_commit = (parts[0], ts, parts[2])
        elif current_commit is not None:
            file_commits[line].append(current_commit)

    # Build stats per file.
    stats: dict[str, GitFileStats] = {}
    for fp, commits in file_commits.items():
        if not commits:
            continue
        timestamps = [c[1] for c in commits]
        authors_list = [c[2] for c in commits]
        author_counts = Counter(authors_list)
        primary = author_counts.most_common(1)[0][0] if author_counts else ""
        churn = sum(1 for c in commits if c[1] >= thirty_days_ago)
        age = int((now - min(timestamps)) / 86400) if timestamps else 0

        stats[fp] = GitFileStats(
            file_path=fp,
            commit_count=len(commits),
            churn_30d=churn,
            last_modified_ts=max(timestamps),
            age_days=age,
            authors=list(author_counts.keys()),
            primary_author=primary,
            last_author=commits[0][2],
        )

    return stats
