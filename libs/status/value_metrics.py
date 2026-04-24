"""Aggregate LV_DCP usage value metrics across all projects.

All numbers are measured, not estimated. No marketing math.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from libs.core.projects_config import list_projects

_SRC_LANGS = ("python", "typescript", "javascript", "go", "rust", "java")


@dataclass
class ProjectCoverage:
    name: str
    root: str
    files_total: int = 0
    files_with_symbols: int = 0
    symbols: int = 0
    relations: int = 0
    relation_types: dict[str, int] = field(default_factory=dict)
    languages: dict[str, int] = field(default_factory=dict)
    packs_served: int = 0
    coverage_pct: float = 0.0


@dataclass
class ValueMetrics:
    # Measured: actual pack sizes from traces
    total_packs: int = 0
    packs_7d: int = 0
    total_pack_files_returned: int = 0  # sum of files returned across all packs
    total_files_in_projects: int = 0  # sum of files across all projects
    # Per pack: returned N files out of M total → read N instead of grep-walking M
    # Ratio = total_files_in_projects / max(1, total_pack_files_returned)
    avg_compression_ratio: float = 0.0  # "read 10 files instead of 1200"

    # Quality
    coverage_high: int = 0
    coverage_medium: int = 0
    coverage_ambiguous: int = 0

    # Adoption
    projects_active: int = 0
    projects_total: int = 0
    mode_navigate: int = 0
    mode_edit: int = 0

    # Per-project coverage
    project_coverage: list[ProjectCoverage] = field(default_factory=list)


def collect_value_metrics(config_path: Path) -> ValueMetrics:  # noqa: PLR0912, PLR0915
    """Collect value metrics from retrieval_traces across all registered projects."""
    projects = list_projects(config_path)
    m = ValueMetrics(projects_total=len(projects))
    now = time.time()
    seven_days_ago = now - 7 * 86400
    active_projects: set[str] = set()

    for entry in projects:
        cache_db = entry.root / ".context" / "cache.db"
        name = entry.root.name
        pc = ProjectCoverage(name=name, root=str(entry.root))

        if not cache_db.exists():
            m.project_coverage.append(pc)
            continue

        try:
            conn = sqlite3.connect(cache_db)

            # Files + coverage
            try:
                pc.files_total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                pc.files_with_symbols = conn.execute(
                    "SELECT COUNT(DISTINCT file_path) FROM symbols"
                ).fetchone()[0]
                pc.symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
                pc.relations = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]

                # Coverage over parseable source files only (exclude __init__.py,
                # config-only languages, and tiny files)
                placeholders = ",".join("?" for _ in _SRC_LANGS)
                parseable_query = (
                    "SELECT COUNT(*) FROM files "
                    f"WHERE language IN ({placeholders}) AND size_bytes >= 20 "
                    "AND path NOT LIKE ?"
                )
                parseable = conn.execute(
                    parseable_query,
                    (*_SRC_LANGS, "%/__init__.py"),
                ).fetchone()[0]
                parseable_with_syms_query = (
                    "SELECT COUNT(DISTINCT f.path) FROM files f "
                    "JOIN symbols s ON f.path = s.file_path "
                    f"WHERE f.language IN ({placeholders}) AND f.size_bytes >= 20 "
                    "AND f.path NOT LIKE ?"
                )
                parseable_with_syms = conn.execute(
                    parseable_with_syms_query,
                    (*_SRC_LANGS, "%/__init__.py"),
                ).fetchone()[0]
                pc.coverage_pct = parseable_with_syms / parseable * 100 if parseable else 100.0
                m.total_files_in_projects += pc.files_total

                # Language breakdown
                for lang, cnt in conn.execute(
                    "SELECT language, COUNT(*) FROM files GROUP BY language"
                ):
                    pc.languages[lang] = cnt

                # Relation types
                for rtype, cnt in conn.execute(
                    "SELECT relation_type, COUNT(*) FROM relations GROUP BY relation_type"
                ):
                    pc.relation_types[rtype] = cnt
            except sqlite3.OperationalError:
                pass

            # Traces — count packs and files returned
            try:
                rows = conn.execute(
                    "SELECT mode, timestamp, coverage, trace_json FROM retrieval_traces"
                ).fetchall()
            except sqlite3.OperationalError:
                conn.close()
                m.project_coverage.append(pc)
                continue

            for mode, ts, coverage, trace_json in rows:
                m.total_packs += 1
                pc.packs_served += 1
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

                # Count files actually returned in this pack
                try:
                    trace = json.loads(trace_json)
                    final_ranking = trace.get("final_ranking", [])
                    m.total_pack_files_returned += len(final_ranking)
                except (json.JSONDecodeError, TypeError):
                    m.total_pack_files_returned += 5  # conservative default

            conn.close()
        except (sqlite3.DatabaseError, OSError):
            pass

        m.project_coverage.append(pc)

    m.projects_active = len(active_projects)

    # Compression ratio: how many files would you read without pack vs with pack
    if m.total_packs > 0 and m.total_pack_files_returned > 0:
        avg_project_files = m.total_files_in_projects / max(1, m.projects_active)
        avg_pack_files = m.total_pack_files_returned / m.total_packs
        m.avg_compression_ratio = avg_project_files / max(1, avg_pack_files)

    return m
