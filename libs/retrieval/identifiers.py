"""Shared identifier/path tokenization helpers for retrieval."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-zA-Z\u0430-\u044f\u0410-\u042f\u0451\u04010-9_.-]+")


def split_identifier_tokens(text: str) -> list[str]:
    """Split text into lowercase identifier-like tokens.

    Handles:
    - path separators and dots
    - snake_case and kebab-case
    - CamelCase boundaries
    """
    out: list[str] = []
    for part in _TOKEN_RE.findall(text):
        for chunk in re.split(r"[_.-]+", part):
            if not chunk:
                continue
            camel_chunks = re.split(r"(?<=[a-z0-9])(?=[A-Z])", chunk)
            out.extend(c.lower() for c in camel_chunks if c)
    return out


def expand_query_terms(query: str) -> list[str]:
    """Return ordered unique raw-ish and identifier-expanded query terms."""
    raw_terms = [term.lower() for term in _TOKEN_RE.findall(query) if term]
    expanded_terms = split_identifier_tokens(query)

    seen: set[str] = set()
    terms: list[str] = []
    for term in [*raw_terms, *expanded_terms]:
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def path_alias_text(path: str) -> str:
    """Return an FTS-friendly alias string derived from a file path."""
    return " ".join(split_identifier_tokens(path))
