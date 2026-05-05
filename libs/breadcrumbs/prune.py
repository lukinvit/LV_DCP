"""TTL + LRU prune helpers."""

from __future__ import annotations

from libs.breadcrumbs.store import BreadcrumbStore


def prune_older_than(*, store: BreadcrumbStore, cutoff_ts: float) -> int:
    """Delete breadcrumbs older than cutoff_ts.

    Args:
        store: BreadcrumbStore instance.
        cutoff_ts: Timestamp cutoff; rows with timestamp < cutoff_ts are deleted.

    Returns:
        Number of rows deleted.
    """
    conn = store.connect()
    cur = conn.execute("DELETE FROM breadcrumbs WHERE timestamp < ?", (cutoff_ts,))
    conn.commit()
    return cur.rowcount or 0


def enforce_per_project_cap(*, store: BreadcrumbStore, project_root: str, max_rows: int) -> int:
    """Enforce per-project LRU cap; delete oldest rows if over limit.

    Args:
        store: BreadcrumbStore instance.
        project_root: Project root path.
        max_rows: Maximum rows to keep per project.

    Returns:
        Number of rows deleted.
    """
    conn = store.connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM breadcrumbs WHERE project_root = ?", (project_root,)
    ).fetchone()[0]
    if count <= max_rows:
        return 0
    overflow = count - max_rows
    cur = conn.execute(
        "DELETE FROM breadcrumbs WHERE id IN ("
        " SELECT id FROM breadcrumbs WHERE project_root = ? "
        " ORDER BY timestamp ASC LIMIT ?"
        ")",
        (project_root, overflow),
    )
    conn.commit()
    return cur.rowcount or 0
