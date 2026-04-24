"""Central status aggregator — shared by FastAPI dashboard and lvdcp_status MCP.

All heavy lifting happens here so dashboard routes and the MCP tool remain thin.
"""

from __future__ import annotations

import json
import os
import posixpath
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
    WikiBackgroundRefresh,
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


_EXPECT_SYMBOLS_LANGUAGES = frozenset(
    {"python", "typescript", "javascript", "go", "rust", "java", "kotlin", "swift"}
)


def _file_expects_symbols(f_path: str, f_language: str, f_size: int) -> bool:
    """Return True if this file is expected to have symbols.

    Excludes empty __init__.py, config-only files (YAML/JSON/TOML),
    and tiny files (< 20 bytes) that are effectively empty.
    """
    if f_language not in _EXPECT_SYMBOLS_LANGUAGES:
        return False
    if f_size < 20:
        return False
    basename = f_path.rsplit("/", 1)[-1]
    return basename != "__init__.py"


def _build_scan_coverage(root: Path) -> dict[str, object] | None:
    """Compute scan coverage stats: symbol/file ratio, languages, relation types.

    Coverage % is calculated only over files that are *expected* to have
    symbols (source code in supported languages, excluding empty __init__.py
    and config files). This gives a more meaningful metric than raw file count.
    """
    try:
        with ProjectIndex.open(root) as idx:
            files = list(idx.iter_files())
            symbols = list(idx.iter_symbols())
            relations = list(idx.iter_relations())
    except (ProjectNotIndexedError, Exception):
        return None

    if not files:
        return None

    files_with_symbols = {s.file_path for s in symbols}
    parseable = [f for f in files if _file_expects_symbols(f.path, f.language, f.size_bytes)]
    parseable_with_symbols = len([f for f in parseable if f.path in files_with_symbols])

    languages: dict[str, int] = {}
    for f in files:
        languages[f.language] = languages.get(f.language, 0) + 1
    relation_types: dict[str, int] = {}
    for r in relations:
        rt = r.relation_type.value if hasattr(r.relation_type, "value") else str(r.relation_type)
        relation_types[rt] = relation_types.get(rt, 0) + 1

    coverage_pct = parseable_with_symbols / len(parseable) * 100 if parseable else 100.0

    return {
        "files_total": len(files),
        "files_with_symbols": len(files_with_symbols),
        "files_parseable": len(parseable),
        "coverage_pct": coverage_pct,
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
    wiki_refresh = build_wiki_refresh(root)

    return ProjectStatus(
        card=card,
        claude_usage_7d=usage_7d,
        claude_usage_30d=usage_30d,
        sparklines=sparklines,
        graph=graph,
        hotspots=hotspots,
        scan_coverage=coverage,
        wiki_refresh=wiki_refresh,
    )


def build_wiki_refresh(root: Path) -> WikiBackgroundRefresh | None:
    """Assemble the bg wiki-refresh snapshot exposed on ``ProjectStatus``.

    Thin mapping over :func:`libs.copilot.wiki_background.read_status` —
    flattens the nested ``last_run`` record into ``last_*`` fields so
    callers (MCP agents, HTMX fragment endpoint, CLI renderers) don't
    need to know the internal dataclass shape. Returns ``None`` on any
    read error (best-effort: a missing or torn lock file shouldn't
    break the whole status payload).

    Public from v0.8.8 onwards so the dashboard's HTMX polling endpoint
    can build *just* this sliver of state without paying for the full
    ``build_project_status`` pipeline (graph, sparklines, hotspots,
    coverage) every ~2 s during a live refresh.
    """
    try:
        # Lazy import: ``libs.copilot`` pulls in the scanning stack, and
        # callers of ``libs.status`` that don't care about wiki refresh
        # shouldn't pay that import cost.
        from libs.copilot.wiki_background import read_status as _read_bg_status  # noqa: PLC0415
    except Exception:
        return None
    try:
        bg = _read_bg_status(root)
    except Exception:
        return None

    last_run = bg.last_run
    log_tail = (
        list(last_run.log_tail)
        if (last_run is not None and last_run.log_tail is not None)
        else None
    )
    return WikiBackgroundRefresh(
        in_progress=bg.in_progress,
        phase=bg.phase,
        modules_total=bg.modules_total,
        modules_done=bg.modules_done,
        current_module=bg.current_module,
        pid=bg.pid,
        last_completed_at=last_run.completed_at if last_run is not None else None,
        last_exit_code=last_run.exit_code if last_run is not None else None,
        last_modules_updated=last_run.modules_updated if last_run is not None else None,
        last_elapsed_seconds=last_run.elapsed_seconds if last_run is not None else None,
        last_log_tail=log_tail,
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


def _load_tsconfig_paths(known_paths: set[str], root: Path) -> dict[str, str]:
    """Pre-load tsconfig.json path aliases from the project.

    Scans known_paths for tsconfig*.json files, reads them from disk,
    parses compilerOptions.paths, and returns a mapping of
    import prefix → filesystem prefix (relative to project root).

    E.g. for tsconfig at "frontend/tsconfig.json" with baseUrl="." and
    paths {"@app/*": ["src/app/*"]}, returns {"@app/": "frontend/src/app/"}.
    """
    mapping: dict[str, str] = {}
    tsconfig_files = [p for p in known_paths if p.endswith("tsconfig.json")]

    for tsconfig_rel in tsconfig_files:
        tsconfig_path = root / tsconfig_rel
        if not tsconfig_path.is_file():
            continue
        try:
            raw = tsconfig_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue

        compiler_opts = data.get("compilerOptions", {})
        paths = compiler_opts.get("paths")
        if not paths:
            continue

        base_url = compiler_opts.get("baseUrl", ".")
        tsconfig_dir = posixpath.dirname(tsconfig_rel)
        # Resolve baseUrl relative to tsconfig directory
        resolved_base = posixpath.normpath(posixpath.join(tsconfig_dir, base_url))
        if resolved_base == ".":
            resolved_base = ""

        for alias_pattern, targets in paths.items():
            if not alias_pattern.endswith("/*") or not targets:
                continue
            target = targets[0]
            if not target.endswith("/*"):
                continue
            # Strip trailing "/*"
            alias_prefix = alias_pattern[:-1]  # "@app/*" → "@app/"
            target_prefix = target[:-1]  # "src/app/*" → "src/app/"
            # Combine with resolved base
            fs_prefix = resolved_base + "/" + target_prefix if resolved_base else target_prefix
            # Normalize (remove ./ etc)
            fs_prefix = posixpath.normpath(fs_prefix) + "/"
            mapping[alias_prefix] = fs_prefix

    return mapping


_TS_JS_EXTENSIONS = ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js")


def _try_resolve_with_extensions(base: str, known_paths: set[str]) -> str | None:
    """Try base path with common TS/JS extensions."""
    for ext in _TS_JS_EXTENSIONS:
        candidate = base + ext
        if candidate in known_paths:
            return candidate
    return None


def _resolve_import_to_file(  # noqa: PLR0911, PLR0912
    src_file: str,
    module_ref: str,
    known_paths: set[str],
    tsconfig_paths: dict[str, str] | None = None,
) -> str | None:
    """Best-effort resolve of an import module ref to a project file path.

    Handles:
    - Python dotted imports: "libs.core.entities" → "libs/core/entities.py"
    - TS/JS relative imports: "./models/user" → resolved relative to src_file
    - TS/JS tsconfig path aliases: "@app/foo" → "frontend/src/app/foo.ts"
    - Go internal imports: looks for suffix match in known_paths
    """
    # Python-style dotted imports (no slashes, no dots in file extensions)
    if "." in module_ref and "/" not in module_ref and not module_ref.startswith("."):
        candidate = module_ref.replace(".", "/") + ".py"
        if candidate in known_paths:
            return candidate
        # Try as package __init__
        candidate_pkg = module_ref.replace(".", "/") + "/__init__.py"
        if candidate_pkg in known_paths:
            return candidate_pkg
        # Symbol import: "libs.core.entities.Symbol" → try "libs/core/entities.py"
        parts = module_ref.split(".")
        for i in range(len(parts) - 1, 0, -1):
            candidate = "/".join(parts[:i]) + ".py"
            if candidate in known_paths:
                return candidate

    # TS/JS relative imports: "./foo", "../bar/baz"
    if module_ref.startswith("./") or module_ref.startswith("../"):
        src_dir = posixpath.dirname(src_file)
        resolved = posixpath.normpath(posixpath.join(src_dir, module_ref))
        result = _try_resolve_with_extensions(resolved, known_paths)
        if result:
            return result

    # TS/JS tsconfig path aliases: "@app/foo", "@shared/ui/Button"
    if tsconfig_paths and not module_ref.startswith("."):
        for alias_prefix, fs_prefix in tsconfig_paths.items():
            if module_ref.startswith(alias_prefix):
                remainder = module_ref[len(alias_prefix) :]
                resolved = fs_prefix + remainder
                result = _try_resolve_with_extensions(resolved, known_paths)
                if result:
                    return result

    # Go internal imports: match suffix (e.g., "myproject/internal/auth" → find "internal/auth/*.go")
    # Just try suffix matching against known paths
    if "/" in module_ref and not module_ref.startswith("."):
        suffix = module_ref.rstrip("/")
        for path in known_paths:
            # Match if path starts with the import suffix (relative to project root)
            path_no_ext = path.rsplit(".", 1)[0] if "." in path.split("/")[-1] else path
            if path_no_ext == suffix or path_no_ext.endswith("/" + suffix):
                return path

    return None


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

    # Pre-load tsconfig path aliases (read once, used in loop)
    tsconfig_paths = _load_tsconfig_paths(seen, root)

    # Map symbols to their defining files (for DEFINES relations)
    symbol_to_file: dict[str, str] = {}
    for rel in relations:
        if rel.src_type == "file" and rel.dst_type == "symbol" and rel.relation_type == "defines":
            symbol_to_file[rel.dst_ref] = rel.src_ref

    edge_pairs: set[tuple[str, str]] = set()
    for rel in relations:
        src_file = rel.src_ref if rel.src_type == "file" else symbol_to_file.get(rel.src_ref)
        dst_file = rel.dst_ref if rel.dst_type == "file" else symbol_to_file.get(rel.dst_ref)

        # For import relations with dst_type="module", try to resolve to a file
        if (
            dst_file is None
            and rel.relation_type == "imports"
            and rel.dst_type == "module"
            and src_file
        ):
            dst_file = _resolve_import_to_file(src_file, rel.dst_ref, seen, tsconfig_paths)

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
