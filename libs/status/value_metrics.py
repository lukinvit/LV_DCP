"""Aggregate LV_DCP usage value metrics across all projects."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from libs.core.projects_config import list_projects


@dataclass
class ValueMetrics:
    total_packs: int = 0
    packs_7d: int = 0
    projects_active: int = 0
    projects_total: int = 0
    estimated_tokens_saved: int = 0
    coverage_high: int = 0
    coverage_medium: int = 0
    coverage_ambiguous: int = 0
    mode_navigate: int = 0
    mode_edit: int = 0
    avg_files_indexed: int = 0


AVG_PACK_TOKENS = 800  # ~2KB pack ~ 800 tokens
AVG_GREP_WALK_TOKENS = 500_000  # conservative: what grep+read costs for a medium project


def collect_value_metrics(config_path: Path) -> ValueMetrics:
    """Collect value metrics from retrieval_traces across all registered projects."""
    projects = list_projects(config_path)
    m = ValueMetrics(projects_total=len(projects))
    now = time.time()
    seven_days_ago = now - 7 * 86400
    active_projects: set[str] = set()
    total_files = 0

    for entry in projects:
        cache_db = entry.root / ".context" / "cache.db"
        if not cache_db.exists():
            continue

        try:
            conn = sqlite3.connect(cache_db)
            # Count files
            try:
                row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
                total_files += row[0] if row else 0
            except sqlite3.OperationalError:
                pass

            # Count traces
            try:
                rows = conn.execute(
                    "SELECT mode, timestamp, coverage FROM retrieval_traces"
                ).fetchall()
            except sqlite3.OperationalError:
                conn.close()
                continue

            for mode, ts, coverage in rows:
                m.total_packs += 1
                if ts >= seven_days_ago:
                    m.packs_7d += 1
                active_projects.add(str(entry.root))
                if coverage == "high":
                    m.coverage_high += 1
                elif coverage == "medium":
                    m.coverage_medium += 1
                else:
                    m.coverage_ambiguous += 1
                if mode == "edit":
                    m.mode_edit += 1
                else:
                    m.mode_navigate += 1
            conn.close()
        except (sqlite3.DatabaseError, OSError):
            continue

    m.projects_active = len(active_projects)
    m.avg_files_indexed = total_files // max(1, m.projects_total)
    # Each pack saved (grep_walk_cost - pack_cost) tokens
    m.estimated_tokens_saved = m.total_packs * (AVG_GREP_WALK_TOKENS - AVG_PACK_TOKENS)
    return m
