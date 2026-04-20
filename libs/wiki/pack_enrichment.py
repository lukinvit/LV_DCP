"""Wiki injection into context packs.

Keyword-matches query against INDEX.md summary lines, reads top matching
articles, and prepends them to the pack markdown.
"""

from __future__ import annotations

import re
from pathlib import Path

_STOP_WORDS = frozenset(
    {
        # English
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
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "from",
        "by",
        "about",
        "as",
        "into",
        "through",
        "and",
        "or",
        "but",
        "not",
        "no",
        "if",
        "then",
        "than",
        "that",
        "this",
        "it",
        "its",
        "how",
        "what",
        "where",
        "when",
        "who",
        "which",
        "why",
        # Russian
        "и",
        "в",
        "не",
        "на",
        "с",
        "что",
        "как",
        "по",
        "это",
        "для",
        "из",
        "или",
        "но",
        "от",
        "при",
        "же",
        "да",
        "его",
        "её",
        "их",
        "он",
        "она",
        "они",
        "мы",
        "вы",
        "я",
        "так",
        "то",
        "бы",
        "ли",
        "уже",
        "до",
        "за",
        "нет",
        "все",
        "был",
        "была",
        "были",
        "есть",
    }
)


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase word tokens, excluding stop words.

    Uses Unicode-aware \\w+ to capture both Latin and Cyrillic words.
    """
    words = set(re.findall(r"\w+", text.lower()))
    return words - _STOP_WORDS


def find_relevant_articles(
    wiki_dir: Path,
    query: str,
    limit: int = 3,
) -> list[tuple[str, str]]:
    """Find wiki articles relevant to query via keyword matching on INDEX.md.

    Returns list of (article_relative_path, article_content) tuples,
    sorted by relevance score descending. At most *limit* results.
    """
    index_path = wiki_dir / "INDEX.md"
    if not index_path.exists():
        return []

    try:
        index_text = index_path.read_text(encoding="utf-8")
    except OSError:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Parse INDEX.md lines: "- [name](modules/file.md) — summary"
    scored: list[tuple[int, str, str]] = []
    for line in index_text.splitlines():
        match = re.match(r"^- \[.+?\]\((.+?)\)(?:\s*—\s*(.*))?$", line)
        if not match:
            continue
        rel_path = match.group(1)
        summary = match.group(2) or ""

        # Score: count of query tokens present in the line (name + summary)
        line_tokens = _tokenize(line)
        score = len(query_tokens & line_tokens)
        if score > 0:
            scored.append((score, rel_path, summary))

    # Sort by score desc, take top N
    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[tuple[str, str]] = []
    for _score, rel_path, _summary in scored[:limit]:
        article_path = wiki_dir / rel_path
        if not article_path.exists():
            continue
        try:
            content = article_path.read_text(encoding="utf-8")
        except OSError:
            continue
        results.append((rel_path, content))

    return results


def enrich_pack_markdown(
    existing_markdown: str,
    wiki_articles: list[tuple[str, str]],
) -> str:
    """Prepend wiki articles section before existing pack content.

    Args:
        existing_markdown: the current pack markdown
        wiki_articles: list of (article_path, content) from find_relevant_articles

    Returns enriched markdown with wiki section prepended.
    """
    if not wiki_articles:
        return existing_markdown

    parts: list[str] = ["## Project knowledge (wiki)", ""]
    for _path, content in wiki_articles:
        parts.append(content.strip())
        parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(existing_markdown)

    return "\n".join(parts)
