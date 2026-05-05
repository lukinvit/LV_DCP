"""Breadcrumb reader — multi-user-scoped queries."""

from __future__ import annotations

import json
from dataclasses import dataclass

from libs.breadcrumbs.models import BreadcrumbView
from libs.breadcrumbs.store import BreadcrumbStore


@dataclass(frozen=True)
class ProjectDigestEntry:
    project_root: str
    last_ts: float
    count: int
    last_query: str | None
    last_mode: str | None


def _row_to_view(row: tuple[object, ...]) -> BreadcrumbView:
    return BreadcrumbView(
        id=row[0],  # type: ignore[arg-type]
        project_root=row[1],  # type: ignore[arg-type]
        timestamp=row[2],  # type: ignore[arg-type]
        source=row[3],  # type: ignore[arg-type]
        cc_session_id=row[4],  # type: ignore[arg-type]
        os_user=row[5],  # type: ignore[arg-type]
        cc_account_email=row[6],  # type: ignore[arg-type]
        query=row[7],  # type: ignore[arg-type]
        mode=row[8],  # type: ignore[arg-type]
        paths_touched=json.loads(row[9]) if row[9] else [],  # type: ignore[arg-type]
        todo_snapshot=json.loads(row[10]) if row[10] else None,  # type: ignore[arg-type]
        turn_summary=row[11],  # type: ignore[arg-type]
    )


_SELECT_COLS = (
    "id, project_root, timestamp, source, cc_session_id, os_user, "
    "cc_account_email, query, mode, paths_touched, todo_snapshot, turn_summary"
)


def load_recent(  # noqa: PLR0913
    *,
    store: BreadcrumbStore,
    project_root: str,
    os_user: str,
    since_ts: float,
    limit: int,
    cc_account_email: str | None = None,
) -> list[BreadcrumbView]:
    """Load recent breadcrumbs for a specific project and user.

    Args:
        store: BreadcrumbStore instance
        project_root: project root path to filter by
        os_user: OS username to filter by
        since_ts: timestamp cutoff (only rows >= this value)
        limit: max rows to return
        cc_account_email: optional Claude account email filter. If provided,
            rows with NULL or matching email are included (best-effort fallback).

    Returns:
        List of BreadcrumbView rows ordered by timestamp DESC.
    """
    conn = store.connect()
    sql_cols = _SELECT_COLS
    if cc_account_email is None:
        rows = conn.execute(
            f"SELECT {sql_cols} FROM breadcrumbs "  # noqa: S608
            "WHERE project_root = ? AND os_user = ? AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (project_root, os_user, since_ts, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {sql_cols} FROM breadcrumbs "  # noqa: S608
            "WHERE project_root = ? AND os_user = ? AND timestamp >= ? "
            "AND (cc_account_email IS NULL OR cc_account_email = ?) "
            "ORDER BY timestamp DESC LIMIT ?",
            (project_root, os_user, since_ts, cc_account_email, limit),
        ).fetchall()
    return [_row_to_view(r) for r in rows]


def load_cross_project(
    *,
    store: BreadcrumbStore,
    os_user: str,
    since_ts: float,
    limit: int,
) -> list[ProjectDigestEntry]:
    """Load digest of recent breadcrumbs across all projects for a user.

    Aggregates by project_root, returning the most recent events first.

    Args:
        store: BreadcrumbStore instance
        os_user: OS username to filter by
        since_ts: timestamp cutoff (only rows >= this value)
        limit: max projects to return

    Returns:
        List of ProjectDigestEntry ordered by last_ts DESC.
    """
    conn = store.connect()
    rows = conn.execute(
        "SELECT project_root, MAX(timestamp) AS last_ts, COUNT(*) AS cnt "
        "FROM breadcrumbs WHERE os_user = ? AND timestamp >= ? "
        "GROUP BY project_root ORDER BY last_ts DESC LIMIT ?",
        (os_user, since_ts, limit),
    ).fetchall()
    out: list[ProjectDigestEntry] = []
    for project_root, last_ts, cnt in rows:
        last = conn.execute(
            "SELECT query, mode FROM breadcrumbs "
            "WHERE project_root = ? AND os_user = ? AND timestamp = ? "
            "ORDER BY id DESC LIMIT 1",
            (project_root, os_user, last_ts),
        ).fetchone()
        out.append(
            ProjectDigestEntry(
                project_root=project_root,
                last_ts=last_ts,
                count=cnt,
                last_query=last[0] if last else None,
                last_mode=last[1] if last else None,
            )
        )
    return out
