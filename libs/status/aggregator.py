"""Central status aggregator — shared by FastAPI dashboard and lvdcp_status MCP.

All heavy lifting happens here so dashboard routes and the MCP tool remain thin.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from libs.claude_usage.aggregator import TokenTotals as _UsageTotals
from libs.claude_usage.aggregator import UsageAggregator
from libs.claude_usage.cache import UsageCache
from libs.claude_usage.path_encoding import encode_project_path
from libs.core.projects_config import list_projects
from libs.impact.hotspots import compute_hotspots as _compute_hotspots
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
    GraphCluster,
    GraphDump,
    GraphEdge,
    GraphFileNode,
    GraphNode,
    HotspotInfo,
    ProjectStatus,
    SparklineSeries,
    TokenTotals,
    WorkspaceStatus,
)

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
DEFAULT_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_USAGE_CACHE_PATH = Path.home() / ".lvdcp" / "claude_usage.db"


def resolve_config_path() -> Path:
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
    config_path = resolve_config_path()
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


def _build_scan_coverage(root: Path) -> dict | None:
    """Compute scan coverage stats: symbol/file ratio, languages, relation types."""
    try:
        with ProjectIndex.open(root) as idx:
            files = list(idx.iter_files())
            symbols = list(idx.iter_symbols())
            relations = list(idx.iter_relations())
    except (ProjectNotIndexedError, Exception):
        return None

    if not files:
        return None

    files_with_symbols = len({s.file_path for s in symbols})
    languages: dict[str, int] = {}
    for f in files:
        languages[f.language] = languages.get(f.language, 0) + 1
    relation_types: dict[str, int] = {}
    for r in relations:
        rt = r.relation_type.value if hasattr(r.relation_type, "value") else str(r.relation_type)
        relation_types[rt] = relation_types.get(rt, 0) + 1

    return {
        "files_total": len(files),
        "files_with_symbols": files_with_symbols,
        "coverage_pct": files_with_symbols / len(files) * 100,
        "symbols": len(symbols),
        "relations": len(relations),
        "languages": dict(sorted(languages.items(), key=lambda x: -x[1])),
        "relation_types": dict(sorted(relation_types.items(), key=lambda x: -x[1])),
    }


def build_project_status(project_root: Path) -> ProjectStatus:
    root = project_root.resolve()
    config_path = resolve_config_path()
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

    hotspots = _build_hotspots(root)
    coverage = _build_scan_coverage(root)

    return ProjectStatus(
        card=card,
        claude_usage_7d=usage_7d,
        claude_usage_30d=usage_30d,
        sparklines=sparklines,
        graph=graph,
        hotspots=hotspots,
        scan_coverage=coverage,
    )


def _build_hotspots(root: Path) -> list[HotspotInfo]:
    """Compute top-10 hotspot files for a project."""
    try:
        with ProjectIndex.open(root) as idx:
            files = list(idx.iter_files())
            relations = list(idx.iter_relations())
            git_stats_list = list(idx._cache.iter_git_stats())
    except (ProjectNotIndexedError, Exception):
        return []

    # Build file-level fan_in / fan_out from relations
    symbol_to_file: dict[str, str] = {}
    for rel in relations:
        if rel.src_type == "file" and rel.dst_type == "symbol" and rel.relation_type == "defines":
            symbol_to_file[rel.dst_ref] = rel.src_ref

    fan_in: dict[str, int] = {}
    fan_out: dict[str, int] = {}
    for rel in relations:
        src_file = rel.src_ref if rel.src_type == "file" else symbol_to_file.get(rel.src_ref)
        dst_file = rel.dst_ref if rel.dst_type == "file" else symbol_to_file.get(rel.dst_ref)
        if src_file and dst_file and src_file != dst_file:
            fan_out[src_file] = fan_out.get(src_file, 0) + 1
            fan_in[dst_file] = fan_in.get(dst_file, 0) + 1

    all_paths = {f.path for f in files}
    file_roles = {f.path: f.role for f in files}
    git_churn = {s.file_path: s.churn_30d for s in git_stats_list}

    # Test coverage: check if a test file exists for source files
    test_paths = {f.path for f in files if f.role == "test"}
    test_coverage: dict[str, bool] = {}
    for fp in all_paths:
        if file_roles.get(fp) != "source":
            continue
        basename = fp.split("/")[-1]
        has_test = any(
            tp.endswith(f"test_{basename}") or tp.endswith(f"{basename.replace('.py', '_test.py')}")
            for tp in test_paths
        )
        test_coverage[fp] = has_test

    source_degrees = {
        fp: (fan_in.get(fp, 0), fan_out.get(fp, 0))
        for fp in all_paths
        if file_roles.get(fp) == "source"
    }

    raw = _compute_hotspots(
        file_degrees=source_degrees,
        git_churn=git_churn,
        test_coverage=test_coverage,
        limit=10,
    )

    return [
        HotspotInfo(
            file_path=h.file_path,
            fan_in=h.fan_in,
            fan_out=h.fan_out,
            churn_30d=h.churn_30d,
            has_tests=h.has_tests,
            score=h.hotspot_score,
        )
        for h in raw
    ]


def _cluster_files(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    max_clusters: int = 50,
    files_per_cluster: int = 20,
) -> list[GraphCluster]:
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.src] = degree.get(e.src, 0) + 1
        degree[e.dst] = degree.get(e.dst, 0) + 1

    buckets: dict[str, list[GraphNode]] = {}
    for n in nodes:
        parts = n.id.split("/")
        cluster_id = (
            "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) == 2 else ".")
        )
        buckets.setdefault(cluster_id, []).append(n)

    node_to_cluster: dict[str, str] = {}
    clusters: list[GraphCluster] = []
    for cid, file_nodes in buckets.items():
        for fn in file_nodes:
            node_to_cluster[fn.id] = cid

        files_with_deg = [(fn, degree.get(fn.id, 0)) for fn in file_nodes]
        files_with_deg.sort(key=lambda x: -x[1])

        roles = [fn.role for fn in file_nodes]
        dominant_role = max(set(roles), key=roles.count) if roles else "code"
        total_deg = sum(d for _, d in files_with_deg)

        top = [
            GraphFileNode(id=fn.id, label=fn.id.split("/")[-1], role=fn.role, degree=d)
            for fn, d in files_with_deg[:files_per_cluster]
        ]

        clusters.append(
            GraphCluster(
                id=cid,
                label=cid,
                role=dominant_role,
                children_count=len(file_nodes),
                total_degree=total_deg,
                top_files=top,
            )
        )

    for e in edges:
        src_c = node_to_cluster.get(e.src)
        dst_c = node_to_cluster.get(e.dst)
        if src_c and dst_c and src_c != dst_c:
            for c in clusters:
                if c.id == src_c:
                    c.inter_cluster_edges += 1
                    break

    clusters.sort(key=lambda c: -c.total_degree)
    return clusters[:max_clusters]


def _build_graph_dump(root: Path) -> GraphDump | None:
    try:
        with ProjectIndex.open(root) as idx:
            files = list(idx.iter_files())
            relations = list(idx.iter_relations())
    except ProjectNotIndexedError:
        return None

    all_nodes: list[GraphNode] = []
    seen: set[str] = set()
    for f in files:
        all_nodes.append(GraphNode(id=f.path, label=f.path, role=_role_for_file(f.path)))
        seen.add(f.path)

    symbol_to_file: dict[str, str] = {}
    for rel in relations:
        if rel.src_type == "file" and rel.dst_type == "symbol" and rel.relation_type == "defines":
            symbol_to_file[rel.dst_ref] = rel.src_ref

    edge_pairs: set[tuple[str, str]] = set()
    for rel in relations:
        src_file = rel.src_ref if rel.src_type == "file" else symbol_to_file.get(rel.src_ref)
        dst_file = rel.dst_ref if rel.dst_type == "file" else symbol_to_file.get(rel.dst_ref)
        if src_file and dst_file and src_file != dst_file and src_file in seen and dst_file in seen:
            edge_pairs.add((src_file, dst_file))

    all_edges = [GraphEdge(src=s, dst=d) for s, d in edge_pairs]
    clusters = _cluster_files(all_nodes, all_edges)
    return GraphDump(nodes=all_nodes, edges=all_edges, clusters=clusters)


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
