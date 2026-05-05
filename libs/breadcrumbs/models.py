"""Frozen dataclasses for breadcrumb events."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class BreadcrumbSource(str, enum.Enum):
    PACK = "pack"
    STATUS = "status"
    HOOK_STOP = "hook_stop"
    HOOK_PRE_COMPACT = "hook_pre_compact"
    HOOK_SUBAGENT_STOP = "hook_subagent_stop"
    MANUAL = "manual"


@dataclass(frozen=True)
class Breadcrumb:
    project_root: str
    timestamp: float
    source: BreadcrumbSource
    os_user: str
    privacy_mode: str = "local_only"
    cc_session_id: str | None = None
    cc_account_email: str | None = None
    query: str | None = None
    mode: str | None = None
    paths_touched: list[str] = field(default_factory=list)
    todo_snapshot: list[dict[str, object]] | None = None
    turn_summary: str | None = None


@dataclass(frozen=True)
class BreadcrumbView:
    """Read-side projection used by reader/renderer."""

    id: int
    project_root: str
    timestamp: float
    source: str
    cc_session_id: str | None
    os_user: str
    cc_account_email: str | None
    query: str | None
    mode: str | None
    paths_touched: list[str]
    todo_snapshot: list[dict[str, object]] | None
    turn_summary: str | None
