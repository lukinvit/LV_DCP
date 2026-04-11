"""Daemon configuration: ~/.lvdcp/config.yaml read/write."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ProjectEntry(BaseModel):
    root: Path
    registered_at_iso: str
    last_scan_at_iso: str | None = None
    last_scan_status: str = "pending"


class DaemonConfig(BaseModel):
    version: int = Field(default=1)
    projects: list[ProjectEntry] = Field(default_factory=list)


def load_config(path: Path) -> DaemonConfig:
    if not path.exists():
        return DaemonConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DaemonConfig.model_validate(data)


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


def list_projects(config_path: Path) -> list[ProjectEntry]:
    return load_config(config_path).projects
