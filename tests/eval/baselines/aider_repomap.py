"""Aider-style repo-map baseline for the eval harness.

Aider (paul-gauthier / Aider-AI) ranks files for its context pack with a
PageRank over a tree-sitter-derived reference graph, personalized toward
the files the user is currently chatting about. See
https://aider.chat/2023/10/22/repomap.html for the canonical description.

This baseline emulates that algorithm on top of LV_DCP's own graph. Why
LV_DCP's graph? We want to compare *ranking strategies*, not parser
quality — so using the same graph holds parsing constant and isolates
the retrieval algorithm. The personalization vector is derived from the
query's identifier tokens, approximating "files the user is asking about".

The baseline intentionally uses only structural centrality. No FTS, no
role weights, no git signals, no path-token boosts — those are LV_DCP's
differentiators and should not be credited to the baseline.
"""

from __future__ import annotations

import atexit
from pathlib import Path

from libs.core.entities import File
from libs.graph.builder import Graph
from libs.graph.centrality import pagerank
from libs.project_index.index import ProjectIndex
from libs.retrieval.identifiers import split_identifier_tokens
from libs.scanning.scanner import scan_project

# File extensions that Aider considers "code" — docs and configs are included
# so the baseline does not get an unfair penalty for surfacing them.
_RETURN_LIMIT = 10

_cached: tuple[Path, ProjectIndex, Graph, list[File]] | None = None


def _build_for(repo: Path) -> tuple[ProjectIndex, Graph, list[File]]:
    global _cached
    if _cached is not None and _cached[0] == repo:
        return _cached[1], _cached[2], _cached[3]

    scan_project(repo, mode="full")
    idx = ProjectIndex.open(repo)

    graph = Graph()
    for rel in idx.iter_relations():
        graph.add_relation(rel)
    files = list(idx.iter_files())

    _cached = (repo, idx, graph, files)
    atexit.register(idx.close)
    return idx, graph, files


def _personalization_from_query(query: str, files: list[File]) -> dict[str, float]:
    """Build a personalization vector favoring files whose identifier tokens
    overlap the query's tokens.

    Note: uses LV_DCP's own ``split_identifier_tokens``. This is a deliberate
    shared dependency so both retrievers see the same token boundaries —
    tokenizer changes affect both sides of the comparison equally.
    """
    query_tokens = set(split_identifier_tokens(query))
    if not query_tokens:
        return {}

    weights: dict[str, float] = {}
    for f in files:
        path_obj = Path(f.path)
        file_tokens = set(
            split_identifier_tokens(path_obj.stem) + split_identifier_tokens(path_obj.parent.name)
        )
        overlap = query_tokens & file_tokens
        if overlap:
            weights[f.path] = float(len(overlap))
    return weights


def aider_baseline_retrieve(
    query: str,
    mode: str,
    repo: Path,
) -> tuple[list[str], list[str]]:
    # `mode` mirrors the RetrievalFn contract but the baseline is
    # intentionally mode-agnostic — it ranks by structural centrality alone.
    _ = mode
    """Retrieve top-N files via personalized PageRank over the relation graph.

    Returns (files, symbols) where *files* is the PageRank-ranked top N and
    *symbols* are the FQ names of symbols defined in those files.
    """
    idx, graph, files = _build_for(repo)

    personalization = _personalization_from_query(query, files)
    scores = pagerank(graph, personalization=personalization or None)

    known_paths = {f.path for f in files}
    file_scores = {path: scores.get(path, 0.0) for path in known_paths}
    ordered = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_files = [path for path, _ in ordered[:_RETURN_LIMIT]]

    top_symbols: list[str] = []
    top_set = set(top_files)
    for sym in idx.iter_symbols():
        if sym.file_path in top_set:
            top_symbols.append(sym.fq_name)
        if len(top_symbols) >= _RETURN_LIMIT:
            break

    return top_files, top_symbols
