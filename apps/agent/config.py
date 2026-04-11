"""Daemon configuration — write helpers. Read side lives in libs/core/projects_config."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Re-export read side for backwards compatibility
from libs.core.projects_config import (
    DaemonConfig,
    ProjectEntry,
    list_projects,
    load_config,
)

__all__ = [
    "DaemonConfig",
    "ProjectEntry",
    "add_project",
    "list_projects",
    "load_config",
    "remove_project",
    "save_config",
    "update_last_scan",
]


def save_config(path: Path, cfg: DaemonConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = cfg.model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def add_project(config_path: Path, root: Path) -> None:
    cfg = load_config(config_path)
    root_resolved = root.resolve()
    if any(p.root == root_resolved for p in cfg.projects):
        return
    cfg.projects.append(
        ProjectEntry(
            root=root_resolved,
            registered_at_iso=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    )
    save_config(config_path, cfg)


def remove_project(config_path: Path, root: Path) -> None:
    cfg = load_config(config_path)
    root_resolved = root.resolve()
    cfg.projects = [p for p in cfg.projects if p.root != root_resolved]
    save_config(config_path, cfg)


def update_last_scan(
    config_path: Path,
    root: Path,
    *,
    status: str,
    ts_iso: str,
) -> None:
    """Update last_scan_at_iso and last_scan_status for a registered project.

    No-op if the project is not registered (graceful for races where the user
    unregistered between scan-start and scan-complete).
    """
    cfg = load_config(config_path)
    root_resolved = root.resolve()
    updated = False
    for entry in cfg.projects:
        if entry.root == root_resolved:
            entry.last_scan_at_iso = ts_iso
            entry.last_scan_status = status
            updated = True
            break
    if updated:
        save_config(config_path, cfg)
