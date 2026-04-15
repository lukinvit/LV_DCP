"""Graph expansion stage for the retrieval pipeline.

Takes a set of seed files (from the keyword match / FTS stages) and walks
the relation graph up to `depth` hops, producing additional candidates
with decayed scores.

Forward walk: what does this file use (imports, calls).
Reverse walk: what uses this file (reverse imports) — finds tests/callers.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from libs.graph.builder import Graph

_FILE_EXTENSIONS = frozenset(
    [
        ".py",
        ".md",
        ".yaml",
        ".yml",
        ".toml",
        ".txt",
        ".json",
        ".rst",
        ".cfg",
        ".ini",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
    ]
)
_PROJECT_ROOTS = frozenset(
    {"src", "libs", "apps", "app", "pkg", "internal", "modules", "tests", "scripts", "docs"}
)


def _looks_like_file_path(node: str) -> bool:
    """Return True if *node* looks like a real file path rather than a module specifier.

    A file path either:
    - ends with a known source/doc file extension, OR
    - starts with a known project-internal root segment (``src/``, ``libs/`` …)

    Rejects:
    - Unresolved relative import specifiers (``./flow-engine``, ``../utils``)
    - tsconfig-style alias imports (``@/lib/foo``)
    - npm package specifiers with subpaths (``next-auth/jwt``, ``@playwright/test``)
    - Symbol FQ-names (``app.services.auth.authenticate``)
    """
    if node.startswith(("./", "../", "@/", "@")):
        return False
    # Known file extension → definitely a file
    dot = node.rfind(".")
    if dot != -1 and node[dot:] in _FILE_EXTENSIONS:
        return True
    # Has slash → accept only if rooted at a project-internal segment
    if "/" in node:
        first_segment = node.split("/", 1)[0]
        return first_segment in _PROJECT_ROOTS
    return False


@dataclass(frozen=True)
class ExpandedCandidate:
    path: str
    score: float
    hop_distance: int
    via: str  # "forward" | "reverse" | "both"


@dataclass
class _WalkContext:
    graph: Graph
    seeds_set: set[str]
    depth: int
    decay: float
    results: dict[str, tuple[float, int, str]]


def expand_via_graph(
    seeds: dict[str, float],
    graph: Graph,
    *,
    depth: int,
    decay: float,
) -> list[ExpandedCandidate]:
    """BFS expansion from seeds in both directions, with score decay.

    Three walk modes:
    - forward:  file → symbol (what this file imports/defines)
    - reverse:  ← file (what imports this file — usually empty for file nodes)
    - mixed:    file → symbol → file  (files that share the same imported symbols)
                This is the primary path for file-to-file discovery since the graph
                stores file→symbol edges (IMPORTS/DEFINES) rather than file→file edges.
    """
    # path -> (best_score, best_hop, via)
    results: dict[str, tuple[float, int, str]] = {}
    ctx = _WalkContext(
        graph=graph,
        seeds_set=set(seeds.keys()),
        depth=depth,
        decay=decay,
        results=results,
    )

    for seed_path, seed_score in seeds.items():
        _walk(ctx, seed_path=seed_path, seed_score=seed_score, reverse=False, direction="forward")
        _walk(ctx, seed_path=seed_path, seed_score=seed_score, reverse=True, direction="reverse")
        _walk_mixed(ctx, seed_path=seed_path, seed_score=seed_score)

    # Filter out symbol FQ-names — keep only file paths.
    # File paths either contain '/' (multi-component) or end with a known
    # file extension.  Symbol FQ-names are dot-separated identifiers with
    # no extension (e.g. "app.services.auth.authenticate").
    return [
        ExpandedCandidate(path=path, score=score, hop_distance=hop, via=via)
        for path, (score, hop, via) in results.items()
        if _looks_like_file_path(path)
    ]


def _walk(
    ctx: _WalkContext,
    *,
    seed_path: str,
    seed_score: float,
    reverse: bool,
    direction: str,
) -> None:
    visited: set[str] = {seed_path}
    queue: deque[tuple[str, int]] = deque([(seed_path, 0)])
    while queue:
        node, hop = queue.popleft()
        if hop >= ctx.depth:
            continue
        neighbors = ctx.graph.reverse_neighbors(node) if reverse else ctx.graph.neighbors(node)
        for nxt in neighbors:
            if nxt in visited:
                continue
            visited.add(nxt)
            if nxt in ctx.seeds_set:
                continue  # don't expand into other seeds
            new_hop = hop + 1
            decayed_score = seed_score * (ctx.decay**new_hop)
            prev = ctx.results.get(nxt)
            if prev is None or decayed_score > prev[0]:
                via = direction if prev is None else ("both" if prev[2] != direction else direction)
                ctx.results[nxt] = (decayed_score, new_hop, via)
            queue.append((nxt, new_hop))


def _file_to_module_prefix(file_path: str) -> str:
    """Convert a file path to the dotted module prefix it defines.

    Examples:
        "app/services/auth.py"  ->  "app.services.auth"
        "tests/test_auth.py"    ->  "tests.test_auth"
    """
    return file_path.replace("/", ".").removesuffix(".py")


def _sym_to_file_path(sym: str) -> str | None:
    """Derive the file path that defines a fully-qualified symbol, if possible.

    We use a simple heuristic: strip the last component (the symbol name) to
    get the module path, then convert to a file path.  Returns ``None`` for
    single-component names or symbols that cannot be a project path.

    Examples:
        "app.services.auth.authenticate"  ->  "app/services/auth.py"
        "fastapi.APIRouter"               ->  "fastapi/APIRouter.py"  (non-project)
        "datetime"                        ->  None
    """
    parts = sym.rsplit(".", 1)
    if len(parts) < 2:
        return None
    module = parts[0]
    # Must look like a multi-component project path (at least 2 dots deep, e.g. app.x.y)
    if module.count(".") < 1:
        return None
    return module.replace(".", "/") + ".py"


def _walk_mixed(
    ctx: _WalkContext,
    *,
    seed_path: str,
    seed_score: float,
) -> None:
    """Mixed forward→reverse walk for file-to-file discovery.

    The graph stores file→symbol edges (IMPORTS/DEFINES) but no direct
    file→file edges.  Two complementary sub-walks recover file-to-file links:

    A) Caller discovery (seed → own symbol → caller file)
       Walk via symbols *owned by* the seed file (FQ name prefixed by the
       seed's module path).  Reverse neighbours of those symbols are files
       that import / use them — i.e., direct callers or dependents.

    B) Dependency discovery (seed → imported symbol → defining file)
       Walk via symbols the seed *imports* whose FQ name encodes a project
       module (multi-component dotted path).  Derive the defining file path
       from the symbol prefix.  This finds the implementation files that the
       seed depends on.

    External library symbols (fastapi.*, sqlalchemy.*, datetime, …) are
    filtered out of sub-walk B because they cannot be mapped to project files.

    Each discovered file is a 2-hop neighbour with decayed score.  Seeds may
    appear in the results — the pipeline takes max(seed_score, mixed_score),
    which boosts a weakly-matching seed when graph evidence confirms relevance.
    """
    direction = "mixed"
    module_prefix = _file_to_module_prefix(seed_path)
    decayed_score = seed_score * (ctx.decay**2)

    seen_files: set[str] = {seed_path}

    # Sub-walk A: own symbols → callers
    own_symbols = [
        sym for sym in ctx.graph.neighbors(seed_path) if sym.startswith(module_prefix + ".")
    ]
    for sym in own_symbols:
        for file_node in ctx.graph.reverse_neighbors(sym):
            if not _looks_like_file_path(file_node) or file_node in seen_files:
                continue
            seen_files.add(file_node)
            prev = ctx.results.get(file_node)
            if prev is None or decayed_score > prev[0]:
                via = direction if prev is None else ("both" if prev[2] != direction else direction)
                ctx.results[file_node] = (decayed_score, 2, via)

    # Sub-walk B: imported project symbols → defining files
    imported_syms = [
        sym for sym in ctx.graph.neighbors(seed_path) if not sym.startswith(module_prefix + ".")
    ]
    for sym in imported_syms:
        defining_file = _sym_to_file_path(sym)
        if defining_file is None or defining_file in seen_files:
            continue
        # Only include if the file actually exists in the graph
        if not ctx.graph.has_node(defining_file):
            continue
        seen_files.add(defining_file)
        if defining_file == seed_path:
            continue
        prev = ctx.results.get(defining_file)
        if prev is None or decayed_score > prev[0]:
            via = direction if prev is None else ("both" if prev[2] != direction else direction)
            ctx.results[defining_file] = (decayed_score, 2, via)
