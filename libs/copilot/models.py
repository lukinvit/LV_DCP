"""Pydantic DTOs for ``libs.copilot``.

Every copilot orchestration function returns one of these. The CLI in
``apps/cli/commands/project_cmd.py`` renders them — both human-readable
and ``--json`` forms — without re-deriving any state.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DegradedMode(str, Enum):  # noqa: UP042  # StrEnum changes __str__ semantics
    """One canonical failure mode the copilot can detect and explain.

    These are the answer to "why is the retrieval result not great?"
    Each mode maps to an actionable CLI suggestion; see
    ``DEGRADED_MODE_HINTS`` in ``orchestrator.py``.
    """

    NOT_SCANNED = "not_scanned"
    STALE_SCAN = "stale_scan"
    WIKI_MISSING = "wiki_missing"
    WIKI_STALE = "wiki_stale"
    QDRANT_OFF = "qdrant_off"
    AMBIGUOUS = "ambiguous"


class CopilotCheckReport(BaseModel):
    """Result of ``ctx project check``.

    A compact, human-friendly snapshot of the project's indexability. No
    new state — every field is derived from existing primitives:
    ``HealthCard``, ``wiki_state``, ``QdrantConfig``.
    """

    project_root: str = Field(description="Absolute path to the project root")
    project_name: str = Field(description="Base name of the project root")
    scanned: bool = Field(description="True when .context/cache.db exists and opens cleanly")
    stale: bool = Field(description="True when last scan is older than STALE_THRESHOLD (24 h)")
    last_scan_at_iso: str | None = Field(
        default=None, description="ISO-8601 timestamp of the last scan, if any"
    )
    files: int = Field(default=0, description="Files in the index (0 when not scanned)")
    symbols: int = Field(default=0, description="Symbols in the index")
    relations: int = Field(default=0, description="Relations in the index")
    wiki_present: bool = Field(description="True when .context/wiki/INDEX.md exists")
    wiki_dirty_modules: int = Field(
        default=0, description="Number of modules with status='dirty' in wiki_state"
    )
    wiki_refresh_in_progress: bool = Field(
        default=False,
        description=(
            "True when ``.context/wiki/.refresh.lock`` is present and owned by a live PID "
            "— i.e. a background wiki refresh spawned via ``--wiki-background`` is running."
        ),
    )
    wiki_refresh_phase: str | None = Field(
        default=None,
        description=(
            "Current phase of an in-progress background refresh: "
            "``starting`` | ``loading`` | ``generating`` | ``finalizing``. "
            "None when no refresh is running."
        ),
    )
    wiki_refresh_modules_total: int | None = Field(
        default=None,
        description=(
            "Total modules the background refresh plans to update. None until the "
            "runner has enumerated dirty modules."
        ),
    )
    wiki_refresh_modules_done: int = Field(
        default=0,
        description="Modules already processed in the current background refresh.",
    )
    wiki_refresh_current_module: str | None = Field(
        default=None,
        description=(
            "Module path currently being (re)generated. None between modules or "
            "when no refresh is running."
        ),
    )
    wiki_refresh_pid: int | None = Field(
        default=None,
        description=(
            "PID of the running wiki-refresh subprocess (so `ctx project wiki --stop` "
            "can target it). None when no refresh is running."
        ),
    )
    wiki_last_refresh_completed_at: float | None = Field(
        default=None,
        description=(
            "Unix timestamp when the most recent background refresh finished, "
            "regardless of outcome. None until at least one refresh has completed."
        ),
    )
    wiki_last_refresh_exit_code: int | None = Field(
        default=None,
        description=(
            "Exit code of the most recent background refresh. 0 = clean; "
            "143 = SIGTERM (cancel via `ctx project wiki --stop`); anything else = crash. "
            "None when no refresh has ever run."
        ),
    )
    wiki_last_refresh_modules_updated: int | None = Field(
        default=None,
        description=(
            "Modules touched by the most recent background refresh. For crashes this "
            "reflects the last progress checkpoint, not the intended total."
        ),
    )
    wiki_last_refresh_elapsed_seconds: float | None = Field(
        default=None,
        description="Wall-clock duration of the most recent background refresh.",
    )
    wiki_last_refresh_log_tail: list[str] | None = Field(
        default=None,
        description=(
            "Last ~20 lines of ``.refresh.log`` captured at runner exit, populated "
            "only when the most recent refresh crashed (non-zero, non-SIGTERM exit). "
            "None for clean / cancelled runs and when no refresh has ever happened."
        ),
    )
    qdrant_enabled: bool = Field(
        description="cfg.qdrant.enabled — vector retrieval availability flag"
    )
    degraded_modes: list[DegradedMode] = Field(
        default_factory=list,
        description="Active degraded modes, in priority order (most severe first)",
    )


class CopilotRefreshReport(BaseModel):
    """Result of ``ctx project refresh`` or ``ctx project wiki --refresh``."""

    project_root: str
    project_name: str
    scanned: bool = Field(description="True when this call ran `ctx scan` successfully")
    scan_files: int = Field(default=0, description="Files scanned (0 when scan skipped)")
    scan_reparsed: int = Field(default=0, description="Files reparsed (cache miss)")
    scan_elapsed_seconds: float = Field(default=0.0)
    wiki_refreshed: bool = Field(description="True when wiki update ran")
    wiki_refresh_background_started: bool = Field(
        default=False,
        description=(
            "True when a background wiki refresh was spawned (detached subprocess). "
            "Mutually exclusive with ``wiki_refreshed=True``."
        ),
    )
    wiki_modules_updated: int = Field(
        default=0, description="Modules touched by the wiki update step"
    )
    messages: list[str] = Field(
        default_factory=list,
        description="Human-readable status lines; empty on clean success",
    )


class CopilotAskReport(BaseModel):
    """Result of ``ctx project ask <path> <query>``.

    Thin envelope around ``lvdcp_pack``'s result plus the degraded modes
    observed during orchestration. The caller can render just
    ``markdown`` for a chat-like experience, or fan the metadata out for
    a dashboard.
    """

    project_root: str
    project_name: str
    query: str
    mode: str = Field(description="navigate | edit — echoed from the pack call")
    markdown: str = Field(description="The assembled pack markdown; empty on hard degrade")
    trace_id: str | None = Field(
        default=None, description="Retrieval trace ID for later ctx explain lookup"
    )
    coverage: str = Field(description="high | medium | ambiguous | unavailable")
    retrieved_files: list[str] = Field(default_factory=list)
    degraded_modes: list[DegradedMode] = Field(
        default_factory=list, description="Active degraded modes, most severe first"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Actionable next-step hints derived from degraded_modes",
    )
