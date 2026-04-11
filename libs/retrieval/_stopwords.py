"""Shared stopword list for retrieval components.

Used by both FtsIndex (query sanitization for FTS5 queries) and SymbolIndex
(tokenization of natural-language queries for symbol scoring). Keeping them in
one place prevents the two lists from drifting apart.
"""

from __future__ import annotations

STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "and",
        "or",
        "but",
        "not",
        "no",
        "nor",
        "so",
        "yet",
        "how",
        "where",
        "which",
        "what",
        "when",
        "who",
        "that",
        "i",
        "it",
        "its",
        "if",
        "as",
        "up",
    }
)
