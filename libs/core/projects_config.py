"""Pure read-side for ~/.lvdcp/config.yaml — project registry.

Lives in libs/core so libs/status and other libs can import it without
violating the apps/ -> libs/ layering rule.
"""

from __future__ import annotations

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


def list_projects(config_path: Path) -> list[ProjectEntry]:
    return load_config(config_path).projects
