"""Russian morphological normalization for FTS indexing and search.

Uses pymorphy3 for Cyrillic tokens, leaves Latin tokens as-is (FTS5
Porter stemmer handles English). Lazy-loads the analyzer on first use
(~50ms init, then ~100K words/sec).
"""

from __future__ import annotations

import re
from typing import Any

_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
_WORD_RE = re.compile(r"[a-zA-Zа-яёА-ЯЁ0-9_]+")
_analyzer: Any | None = None


def _get_analyzer() -> Any:
    global _analyzer  # noqa: PLW0603
    if _analyzer is None:
        import pymorphy3  # noqa: PLC0415

        _analyzer = pymorphy3.MorphAnalyzer()
    return _analyzer


def normalize_token(token: str) -> str:
    """Normalize a single token. Cyrillic → pymorphy3 normal form, else lowercase."""
    if not token:
        return ""
    if _CYRILLIC_RE.search(token):
        morph = _get_analyzer()
        parsed = morph.parse(token.lower())
        return parsed[0].normal_form if parsed else token.lower()
    return token.lower()


def normalize_query(query: str) -> str:
    """Normalize a search query — each word independently."""
    return " ".join(normalize_token(t) for t in query.split() if t)


def normalize_text(text: str) -> str:
    """Normalize text for FTS indexing.

    Preserves non-word characters (newlines, punctuation, indentation)
    so FTS5 tokenizer can still split correctly. Only replaces word
    tokens with their normalized forms.
    """

    def _replace(m: re.Match[str]) -> str:
        return normalize_token(m.group(0))

    return _WORD_RE.sub(_replace, text)
