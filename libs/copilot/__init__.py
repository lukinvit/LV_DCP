"""Project Copilot Wrapper — high-level orchestration over LV_DCP primitives.

Public surface:

- ``check_project``   — one-shot health + capability snapshot.
- ``refresh_project`` — scan (+ optional wiki update) in one call.
- ``refresh_wiki``    — wiki-only refresh, thin wrapper.
- ``ask_project``     — delegate to ``lvdcp_pack`` + decorate with
  degraded-mode explanations.

Spec: ``specs/011-project-copilot-wrapper/spec.md``.
"""

from __future__ import annotations

from libs.copilot.models import (
    CopilotAskReport,
    CopilotCheckReport,
    CopilotRefreshReport,
    DegradedMode,
)
from libs.copilot.orchestrator import (
    ask_project,
    check_project,
    refresh_project,
    refresh_wiki,
    watch_check_project,
)
from libs.copilot.wiki_background import (
    BackgroundRefreshStatus,
    LastRefreshRecord,
    cancel_background_refresh,
    is_refresh_in_progress,
    read_last_refresh,
    read_status,
    start_background_refresh,
    write_last_refresh,
)

__all__ = [
    "BackgroundRefreshStatus",
    "CopilotAskReport",
    "CopilotCheckReport",
    "CopilotRefreshReport",
    "DegradedMode",
    "LastRefreshRecord",
    "ask_project",
    "cancel_background_refresh",
    "check_project",
    "is_refresh_in_progress",
    "read_last_refresh",
    "read_status",
    "refresh_project",
    "refresh_wiki",
    "start_background_refresh",
    "watch_check_project",
    "write_last_refresh",
]
