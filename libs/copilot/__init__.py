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
)

__all__ = [
    "CopilotAskReport",
    "CopilotCheckReport",
    "CopilotRefreshReport",
    "DegradedMode",
    "ask_project",
    "check_project",
    "refresh_project",
    "refresh_wiki",
]
