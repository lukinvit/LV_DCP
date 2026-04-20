"""Suggest concrete query refinements when retrieval coverage is ambiguous.

When `compute_coverage` returns "ambiguous", the user gets a flat candidate
list and no hint on how to tighten the query. This helper inspects the
candidate paths and proposes up to a handful of identifier tokens whose
addition would most strongly partition the candidate set.

The logic is deliberately small and deterministic — it surfaces *existing*
path tokens rather than proposing novel ones, so suggestions are
reproducible across runs and easy to audit.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from libs.retrieval.identifiers import split_identifier_tokens

DEFAULT_MAX_SUGGESTIONS = 3
_GENERIC_TOKENS: frozenset[str] = frozenset(
    {
        "src",
        "lib",
        "libs",
        "app",
        "apps",
        "test",
        "tests",
        "docs",
        "doc",
        "py",
        "ts",
        "js",
        "go",
        "rs",
        "pkg",
        "internal",
        "main",
        "init",
        "index",
    }
)


def suggest_disambiguators(
    query: str,
    files: list[str],
    *,
    limit: int = DEFAULT_MAX_SUGGESTIONS,
) -> list[str]:
    """Return up to *limit* path-tokens that would most sharpen *query*.

    A token is a candidate if:
    - it appears in at least one retrieved file's path,
    - it does not already appear in the query's identifier tokens,
    - it is not in the generic-stopwords list (src, lib, test, ...).

    Tokens are ranked by how *discriminative* they are: a token that appears
    in exactly half of the candidates splits the set most evenly and is the
    most informative refinement. Ties break on token frequency (higher is
    more anchored in the corpus) and then alphabetically for determinism.
    """
    if not files or limit <= 0:
        return []

    query_tokens = set(split_identifier_tokens(query))

    token_to_files: dict[str, set[str]] = {}
    for path in files:
        po = PurePosixPath(path)
        path_tokens = set(
            split_identifier_tokens(po.stem) + split_identifier_tokens(str(po.parent))
        )
        for t in path_tokens:
            if t in query_tokens or t in _GENERIC_TOKENS or len(t) < 3:
                continue
            token_to_files.setdefault(t, set()).add(path)

    if not token_to_files:
        return []

    n = len(files)
    half = n / 2.0
    ranked: list[tuple[float, int, str]] = []
    for token, paths in token_to_files.items():
        coverage = len(paths)
        if coverage == n:
            # Token is in every candidate — useless as a disambiguator.
            continue
        # Distance from half-split: lower is better.
        distinctiveness = abs(coverage - half)
        ranked.append((distinctiveness, -coverage, token))

    ranked.sort()
    return [token for _, _, token in ranked[:limit]]


def format_suggestion_hint(suggestions: list[str]) -> str:
    """Render *suggestions* into a short markdown bullet line.

    Returns an empty string when there is nothing useful to say.
    """
    if not suggestions:
        return ""
    if len(suggestions) == 1:
        return f"Try adding **`{suggestions[0]}`** to narrow the query."
    quoted = ", ".join(f"**`{s}`**" for s in suggestions)
    return f"Try adding one of {quoted} to narrow the query."
