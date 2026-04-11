"""Build per-project HealthCard DTOs."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from libs.core.projects_config import list_projects
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError
from libs.status.models import HealthCard

STALE_THRESHOLD = timedelta(hours=24)

_slug_re = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _slug_re.sub("-", name.lower()).strip("-")
    return s or "project"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_health_card(
    project_root: Path,
    *,
    config_path: Path,
) -> HealthCard:
    """Assemble a HealthCard from .context/cache.db + config.yaml state."""
    root = project_root.resolve()
    entry = next(
        (e for e in list_projects(config_path) if e.root == root),
        None,
    )

    files = symbols = relations = 0
    try:
        with ProjectIndex.open(root) as idx:
            files = sum(1 for _ in idx.iter_files())
            symbols = sum(1 for _ in idx.iter_symbols())
            relations = sum(1 for _ in idx.iter_relations())
    except ProjectNotIndexedError:
        pass

    last_scan_iso = entry.last_scan_at_iso if entry else None
    last_scan_status = entry.last_scan_status if entry else "unregistered"

    last_scan_dt = _parse_iso(last_scan_iso)
    stale = False
    if last_scan_dt is not None:
        age = datetime.now(UTC) - last_scan_dt
        stale = age > STALE_THRESHOLD

    return HealthCard(
        root=str(root),
        name=root.name,
        slug=_slugify(root.name),
        files=files,
        symbols=symbols,
        relations=relations,
        last_scan_at_iso=last_scan_iso,
        last_scan_status=last_scan_status,
        stale=stale,
    )
