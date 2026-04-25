"""Per-entry audit of `~/.lvdcp/config.yaml` project registry.

Read-side view used by `ctx registry ls`. Each `ProjectAudit` row
combines:

- static info from the registry entry (name, root, last_scan_at_iso)
- derived classification (real vs transient via `is_transient`)
- live presence check (`.context/cache.db` on disk?)
- activity signal (packs served in the last 7 days)

No mutation. No network. Deliberately non-destructive so we can surface
stale registry entries to the user without auto-pruning them. Auto-prune
is a separate, gated operation (requires explicit `--yes` confirmation)
and is not implemented here.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from libs.core.projects_config import is_transient, list_projects


@dataclass
class ProjectAudit:
    name: str
    root: str
    kind: str  # "real" | "transient"
    scanned: bool  # .context/cache.db exists?
    packs_7d: int
    packs_total: int
    last_scan_at_iso: str | None
    last_scan_age_hours: float | None
    missing: bool = False  # root directory absent on disk? (v0.8.37)


def _parse_iso(ts: str | None) -> float | None:
    """Parse an ISO-8601 UTC timestamp to epoch seconds, or None on junk."""
    if not ts:
        return None
    try:
        # Normalize the trailing "Z" that `datetime.isoformat()` doesn't emit.
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).timestamp()
    except (ValueError, TypeError):
        return None


def _count_packs(cache_db: Path, *, now: float, seven_days_ago: float) -> tuple[int, int]:
    """Return (total_packs, packs_7d) from retrieval_traces.

    Returns (0, 0) on any error — a corrupt DB shouldn't crash the audit.
    """
    try:
        conn = sqlite3.connect(cache_db)
    except sqlite3.DatabaseError:
        return 0, 0
    try:
        total = conn.execute("SELECT COUNT(*) FROM retrieval_traces").fetchone()[0]
        recent = conn.execute(
            "SELECT COUNT(*) FROM retrieval_traces WHERE timestamp >= ?",
            (seven_days_ago,),
        ).fetchone()[0]
    except sqlite3.OperationalError:
        conn.close()
        return 0, 0
    conn.close()
    return int(total), int(recent)


def audit_registry(
    config_path: Path,
    *,
    now: float | None = None,
) -> list[ProjectAudit]:
    """Return one `ProjectAudit` row per registered project.

    Ordering follows the registry file (preserves user's own structure).
    `now` is injectable for deterministic tests.
    """
    current = now if now is not None else time.time()
    seven_days_ago = current - 7 * 86400
    rows: list[ProjectAudit] = []
    for entry in list_projects(config_path):
        # Compute root-presence and cache-presence independently:
        # a tombstone (root gone from disk) has `missing=True` regardless of
        # whether `.context/cache.db` would exist if the root still did.
        missing = not entry.root.exists()
        cache_db = entry.root / ".context" / "cache.db"
        scanned = (not missing) and cache_db.exists()
        total, recent = (
            _count_packs(cache_db, now=current, seven_days_ago=seven_days_ago)
            if scanned
            else (0, 0)
        )
        last_scan_ts = _parse_iso(entry.last_scan_at_iso)
        age_hours = max(0.0, (current - last_scan_ts) / 3600.0) if last_scan_ts else None
        rows.append(
            ProjectAudit(
                name=entry.root.name,
                root=str(entry.root),
                kind="transient" if is_transient(entry.root) else "real",
                scanned=scanned,
                packs_7d=recent,
                packs_total=total,
                last_scan_at_iso=entry.last_scan_at_iso,
                last_scan_age_hours=age_hours,
                missing=missing,
            )
        )
    return rows


def is_stale(row: ProjectAudit, *, older_than_days: int = 30) -> bool:
    """Heuristic: packs_total == 0 and last scan older than `older_than_days`.

    This is the candidate set for future pruning — but pruning itself is
    NOT performed here. Callers get visibility, not deletion.
    """
    if row.packs_total > 0:
        return False
    if row.last_scan_age_hours is None:
        # Never scanned — treat as stale so it shows up in --stale listings.
        return True
    return row.last_scan_age_hours >= older_than_days * 24


def is_missing(row: ProjectAudit) -> bool:
    """Row's registered root directory is absent on disk.

    Companion to ``is_stale``: surfaces tombstones (deleted worktrees,
    moved folders) that the staleness gate would take 30 days to notice.
    Independent of ``kind`` and scan age. Pure read — no mutation.
    """
    return row.missing


def iso_utc(ts: float) -> str:
    """Helper for tests: epoch → ISO-8601 with trailing Z."""
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def backup_status(
    config_path: Path,
    *,
    backup_suffix: str = ".bak",
    now: float | None = None,
) -> tuple[Path | None, float | None]:
    """Return ``(backup_path, age_seconds)`` for the prune-undo sidecar.

    `prune --yes` writes a sibling ``<config>.bak`` snapshot of the
    pre-mutation registry; `restore` reads it back. This helper lets the
    `ls` text renderer surface the backup's existence + age as a footer,
    making the `restore` recovery handle discoverable without forcing
    users to read `prune --yes` output.

    Returns ``(None, None)`` when no backup exists. ``age_seconds`` is
    ``mtime`` delta from ``now`` (or ``time.time()`` when ``now`` is
    omitted), clamped to non-negative for clock-skew safety.

    Pure read — never mutates either file. ``now`` is injectable for
    deterministic tests.
    """
    backup_path = config_path.with_name(config_path.name + backup_suffix)
    if not backup_path.exists():
        return None, None
    current = now if now is not None else time.time()
    age = max(0.0, current - backup_path.stat().st_mtime)
    return backup_path, age
