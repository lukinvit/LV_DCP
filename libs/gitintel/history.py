"""Read recent git history for context-aware agent flows.

Complements :mod:`libs.gitintel.extractor` — the extractor aggregates churn
statistics, this module returns the raw commit stream filtered by time and
optionally by a file prefix. Agents use it to answer "what changed in this
pack's files last week" without grepping the repo.

One subprocess call per invocation. Non-git directories return an empty
list. Timeouts and non-zero exits also return empty — never raise — so the
MCP tool wrapping this never fails on transient git weirdness.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class HistoryCommit:
    sha: str
    author: str
    date_iso: str
    subject: str
    files: tuple[str, ...]


def read_recent_history(
    root: Path,
    *,
    since_days: int = 7,
    filter_path: str | None = None,
    limit: int = 20,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[HistoryCommit]:
    """Return the most recent commits touching *root*, sorted newest-first.

    - *since_days* limits to commits in the last N days (default 7).
    - *filter_path* (relative POSIX path) narrows output to commits that
      touched files under that prefix. ``None`` returns all commits.
    - *limit* caps the number of returned commits.
    """
    if not (root / ".git").is_dir():
        return []
    if limit <= 0:
        return []

    cmd = [
        "git",
        "log",
        f"--since={since_days} days ago",
        f"--max-count={limit}",
        "--format=%H%x1f%aI%x1f%aN%x1f%s",
        "--name-only",
    ]
    if filter_path:
        cmd.extend(["--", filter_path])

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    return list(_parse_log(result.stdout))


def _parse_log(stdout: str) -> list[HistoryCommit]:
    """Parse ``--format=%H%x1f%aI%x1f%aN%x1f%s --name-only`` output.

    The format uses the ASCII unit separator (x1f) between header fields so
    commit subjects containing pipes or tabs can't confuse the parser.
    Blank lines separate commits from file lists.
    """
    entries: list[HistoryCommit] = []
    pending_header: tuple[str, str, str, str] | None = None
    pending_files: list[str] = []

    def flush() -> None:
        if pending_header is None:
            return
        sha, iso, author, subject = pending_header
        entries.append(
            HistoryCommit(
                sha=sha,
                author=author,
                date_iso=iso,
                subject=subject,
                files=tuple(pending_files),
            )
        )

    for raw in stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if "\x1f" in line:
            # New commit header; flush previous.
            flush()
            parts = line.split("\x1f", 3)
            if len(parts) == 4:
                # Normalize date — accept any ISO and canonicalize to UTC.
                try:
                    iso = datetime.fromisoformat(parts[1]).astimezone(UTC).isoformat()
                except ValueError:
                    iso = parts[1]
                pending_header = (parts[0], iso, parts[2], parts[3])
                pending_files = []
        elif pending_header is not None:
            pending_files.append(line)

    flush()
    return entries
