"""Pydantic DTOs for the status layer."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenTotals(BaseModel):
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0


class DaemonStatus(BaseModel):
    state: str  # "running" | "not_loaded" | "error"
    detail: str = ""


class HealthCard(BaseModel):
    root: str
    name: str
    slug: str
    files: int
    symbols: int
    relations: int
    last_scan_at_iso: str | None = None
    last_scan_status: str = "pending"
    stale: bool = False
    obsidian_last_sync_at_iso: str | None = Field(
        default=None,
        description=(
            "ISO 8601 UTC timestamp of the most recent Obsidian sync, derived "
            "from ``.context/obsidian_last_sync`` (a unix-epoch float written "
            "by both the after-scan daemon worker and ``ctx obsidian sync-all``). "
            "``None`` when the marker is missing or unreadable — Obsidian sync "
            "is disabled or has never run for this project."
        ),
    )
    obsidian_sync_age_hours: float | None = Field(
        default=None,
        description=(
            "Age of the most recent Obsidian sync in hours, relative to now. "
            "Precomputed so the dashboard template can render ``Xh ago`` "
            "without doing datetime math in Jinja. ``None`` when the marker "
            "is missing."
        ),
    )


class SparklineSeries(BaseModel):
    metric: str  # "queries" | "scans" | "latency_p95_ms" | "coverage"
    window: str  # "7d" | "30d"
    buckets: list[float] = Field(default_factory=list)
    bucket_labels: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    role: str = "code"  # "code" | "test" | "config" | "docs"


class GraphEdge(BaseModel):
    src: str
    dst: str


class GraphFileNode(BaseModel):
    id: str
    label: str
    role: str = "code"
    degree: int = 0


class GraphCluster(BaseModel):
    id: str
    label: str
    role: str
    children_count: int
    total_degree: int
    inter_cluster_edges: int = 0
    top_files: list[GraphFileNode] = Field(default_factory=list)


class GraphDump(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    clusters: list[GraphCluster] = Field(default_factory=list)


class HotspotInfo(BaseModel):
    file_path: str
    fan_in: int
    fan_out: int
    churn_30d: int
    has_tests: bool
    score: float


class WikiBackgroundRefresh(BaseModel):
    """Background wiki refresh observability for MCP consumers.

    Mirrors the ``wiki_refresh_*`` / ``wiki_last_refresh_*`` fields that
    :class:`libs.copilot.CopilotCheckReport` already surfaces on the CLI
    side, so an agent calling ``lvdcp_status`` sees the same state a
    human sees from ``ctx project check``.

    All fields are nullable on purpose: ``in_progress=False`` with every
    other field ``None`` means "nothing running, never ran"; a running
    refresh populates the live-progress fields; a finished refresh
    populates the ``last_*`` fields. The two sets can be populated at
    the same time — a new refresh that starts right after an old one
    crashed will have both the live progress *and* the last-run tail.
    """

    in_progress: bool = Field(
        default=False,
        description=(
            "True when ``.context/wiki/.refresh.lock`` is present and owned "
            "by a live PID — matches ``CopilotCheckReport.wiki_refresh_in_progress``."
        ),
    )
    phase: str | None = Field(
        default=None,
        description=(
            "Current phase of an in-progress refresh: "
            "``starting`` | ``loading`` | ``generating`` | ``finalizing``."
        ),
    )
    modules_total: int | None = Field(
        default=None,
        description="Total modules the runner plans to update; None until enumerated.",
    )
    modules_done: int = Field(
        default=0, description="Modules already processed in the current refresh."
    )
    current_module: str | None = Field(
        default=None, description="Module currently being (re)generated, if any."
    )
    pid: int | None = Field(
        default=None, description="PID of the running runner, or None when idle."
    )
    last_completed_at: float | None = Field(
        default=None,
        description="Unix ts when the most recent refresh finished, regardless of outcome.",
    )
    last_exit_code: int | None = Field(
        default=None,
        description=(
            "Exit code of the most recent refresh. 0 = clean; 143 = SIGTERM; "
            "anything else = crash. None when no refresh has ever run."
        ),
    )
    last_modules_updated: int | None = Field(
        default=None,
        description=(
            "Modules touched by the most recent refresh; for crashes this reflects "
            "the last progress checkpoint, not the intended total."
        ),
    )
    last_elapsed_seconds: float | None = Field(
        default=None, description="Wall-clock duration of the most recent refresh."
    )
    last_log_tail: list[str] | None = Field(
        default=None,
        description=(
            "Last ~20 lines of ``.refresh.log`` captured at runner exit, populated "
            "only when the most recent refresh crashed (non-zero, non-SIGTERM exit). "
            "None for clean / cancelled runs and when no refresh has ever happened."
        ),
    )


class ProjectStatus(BaseModel):
    card: HealthCard
    claude_usage_7d: TokenTotals
    claude_usage_30d: TokenTotals
    sparklines: list[SparklineSeries] = Field(default_factory=list)
    graph: GraphDump | None = None
    hotspots: list[HotspotInfo] = Field(default_factory=list)
    scan_coverage: dict[str, object] | None = None
    wiki_refresh: WikiBackgroundRefresh | None = Field(
        default=None,
        description=(
            "Background wiki-refresh observability block. None on projects that "
            "predate v0.8.1 or when the status layer couldn't read the lock / "
            "``.refresh.last`` file; a concrete value means the aggregator checked "
            "and found either an idle project or live / historical refresh state."
        ),
    )


class WorkspaceStatus(BaseModel):
    projects_count: int
    total_files: int
    total_symbols: int
    total_relations: int
    daemon: DaemonStatus
    claude_usage_7d: TokenTotals
    claude_usage_30d: TokenTotals
    projects: list[HealthCard] = Field(default_factory=list)


class BudgetInfo(BaseModel):
    spent_7d: float = 0.0
    spent_30d: float = 0.0
    monthly_limit: float = 25.0
    status: str = "disabled"  # "ok" | "warning" | "exceeded" | "disabled"
