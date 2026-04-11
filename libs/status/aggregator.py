"""Central status aggregator — shared by FastAPI dashboard and lvdcp_status MCP.

All heavy lifting happens here so dashboard routes and the MCP tool remain thin.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from apps.agent.config import list_projects

from libs.claude_usage.aggregator import TokenTotals as _UsageTotals
from libs.claude_usage.aggregator import UsageAggregator
from libs.claude_usage.cache import UsageCache
from libs.claude_usage.path_encoding import encode_project_path
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError
from libs.retrieval.trace import query_traces_since
from libs.scan_history.store import (
    ScanHistoryStore,
    events_since,
    resolve_default_store_path,
)
from libs.status.daemon_probe import probe_daemon
from libs.status.health import build_health_card
from libs.status.models import (
    GraphDump,
    GraphEdge,
    GraphNode,
    ProjectStatus,
    SparklineSeries,
    TokenTotals,
    WorkspaceStatus,
)

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
DEFAULT_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_USAGE_CACHE_PATH = Path.home() / ".lvdcp" / "claude_usage.db"


def _resolve_config_path() -> Path:
    override = os.environ.get("LVDCP_CONFIG_PATH")
    return Path(override) if override else DEFAULT_CONFIG_PATH


def _resolve_claude_projects_dir() -> Path:
    override = os.environ.get("LVDCP_CLAUDE_PROJECTS_DIR")
    return Path(override) if override else DEFAULT_CLAUDE_PROJECTS_DIR


def _resolve_usage_cache_path() -> Path:
    override = os.environ.get("LVDCP_USAGE_CACHE_DB")
    return Path(override) if override else DEFAULT_USAGE_CACHE_PATH


def _totals_to_dto(t: _UsageTotals) -> TokenTotals:
    """Bridge dataclass TokenTotals (libs/claude_usage) to pydantic DTO (libs/status)."""
    return TokenTotals(
        input_tokens=t.input_tokens,
        cache_creation_input_tokens=t.cache_creation_input_tokens,
        cache_read_input_tokens=t.cache_read_input_tokens,
        output_tokens=t.output_tokens,
    )


def _usage_totals_for_root(
    aggregator: UsageAggregator,
    root: Path,
    *,
    since_ts: float,
) -> TokenTotals:
    encoded = encode_project_path(root)
    return _totals_to_dto(aggregator.rolling_window(encoded, since_ts=since_ts))


def _role_for_file(path: str) -> str:
    if "/tests/" in path or path.startswith("tests/") or path.startswith("test_"):
        return "test"
    if path.endswith((".md", ".rst", ".txt")):
        return "docs"
    if path.endswith((".yaml", ".yml", ".toml", ".json", ".ini", ".cfg")):
        return "config"
    return "code"


def build_workspace_status() -> WorkspaceStatus:
    config_path = _resolve_config_path()
    claude_dir = _resolve_claude_projects_dir()
    cache_path = _resolve_usage_cache_path()

    cache = UsageCache(cache_path)
    cache.migrate()
    aggregator = UsageAggregator(cache, projects_dir=claude_dir)

    now = time.time()
    ts_7d = now - 7 * 86400
    ts_30d = now - 30 * 86400

    cards = []
    total_files = total_symbols = total_relations = 0
    for entry in list_projects(config_path):
        card = build_health_card(entry.root, config_path=config_path)
        cards.append(card)
        total_files += card.files
        total_symbols += card.symbols
        total_relations += card.relations

    global_7d = aggregator.global_rolling_window(since_ts=ts_7d)
    global_30d = aggregator.global_rolling_window(since_ts=ts_30d)

    cache.close()

    return WorkspaceStatus(
        projects_count=len(cards),
        total_files=total_files,
        total_symbols=total_symbols,
        total_relations=total_relations,
        daemon=probe_daemon(),
        claude_usage_7d=_totals_to_dto(global_7d),
        claude_usage_30d=_totals_to_dto(global_30d),
        projects=cards,
    )


def build_project_status(project_root: Path) -> ProjectStatus:
    root = project_root.resolve()
    config_path = _resolve_config_path()
    claude_dir = _resolve_claude_projects_dir()
    cache_path = _resolve_usage_cache_path()

    card = build_health_card(root, config_path=config_path)

    cache = UsageCache(cache_path)
    cache.migrate()
    aggregator = UsageAggregator(cache, projects_dir=claude_dir)

    now = time.time()
    usage_7d = _usage_totals_for_root(aggregator, root, since_ts=now - 7 * 86400)
    usage_30d = _usage_totals_for_root(aggregator, root, since_ts=now - 30 * 86400)

    cache.close()

    graph = _build_graph_dump(root)
    sparklines = _build_sparklines(root, now=now)

    return ProjectStatus(
        card=card,
        claude_usage_7d=usage_7d,
        claude_usage_30d=usage_30d,
        sparklines=sparklines,
        graph=graph,
    )


def _build_graph_dump(root: Path) -> GraphDump | None:
    try:
        with ProjectIndex.open(root) as idx:
            files = list(idx.iter_files())
            relations = list(idx.iter_relations())
    except ProjectNotIndexedError:
        return None

    nodes: list[GraphNode] = []
    seen: set[str] = set()
    for f in files[:200]:  # cap for payload budget
        nodes.append(GraphNode(id=f.path, label=f.path, role=_role_for_file(f.path)))
        seen.add(f.path)

    edges: list[GraphEdge] = []
    for rel in relations:
        if rel.src_ref in seen and rel.dst_ref in seen:
            edges.append(GraphEdge(src=rel.src_ref, dst=rel.dst_ref))

    return GraphDump(nodes=nodes, edges=edges)


def _build_sparklines(root: Path, *, now: float) -> list[SparklineSeries]:
    since_7d = now - 7 * 86400
    history_store = ScanHistoryStore(resolve_default_store_path())
    history_store.migrate()
    scan_events = events_since(history_store, project_root=str(root), since_ts=since_7d)
    history_store.close()

    traces = []
    try:
        with ProjectIndex.open(root) as idx:
            traces = query_traces_since(idx._cache, project=root.name, since_ts=since_7d)
    except ProjectNotIndexedError:
        pass

    day_buckets = 7
    queries = [0.0] * day_buckets
    scans = [0.0] * day_buckets
    latency = [0.0] * day_buckets
    coverage = [0.0] * day_buckets
    coverage_counts = [0] * day_buckets

    def _bucket(ts: float) -> int:
        idx_val = int((ts - since_7d) / 86400)
        return max(0, min(day_buckets - 1, idx_val))

    for ev in scan_events:
        scans[_bucket(ev.timestamp)] += 1

    coverage_score_map = {"high": 1.0, "medium": 0.5, "ambiguous": 0.25}
    for tr in traces:
        b = _bucket(tr.timestamp)
        queries[b] += 1
        total_ms = sum(s.elapsed_ms for s in tr.stages)
        latency[b] = max(latency[b], total_ms)
        coverage[b] += coverage_score_map.get(tr.coverage, 0.0)
        coverage_counts[b] += 1

    coverage_avg = [
        (coverage[i] / coverage_counts[i]) if coverage_counts[i] else 0.0
        for i in range(day_buckets)
    ]

    labels = [str(i) for i in range(day_buckets)]

    return [
        SparklineSeries(metric="queries", window="7d", buckets=queries, bucket_labels=labels),
        SparklineSeries(metric="scans", window="7d", buckets=scans, bucket_labels=labels),
        SparklineSeries(
            metric="latency_p95_ms", window="7d", buckets=latency, bucket_labels=labels
        ),
        SparklineSeries(metric="coverage", window="7d", buckets=coverage_avg, bucket_labels=labels),
    ]
