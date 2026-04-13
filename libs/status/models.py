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


class ProjectStatus(BaseModel):
    card: HealthCard
    claude_usage_7d: TokenTotals
    claude_usage_30d: TokenTotals
    sparklines: list[SparklineSeries] = Field(default_factory=list)
    graph: GraphDump | None = None
    hotspots: list[HotspotInfo] = Field(default_factory=list)
    scan_coverage: dict[str, object] | None = None


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
