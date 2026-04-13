"""INDEX.md generation from wiki articles."""

from __future__ import annotations

import re
import time
from pathlib import Path


def _extract_purpose_first_sentence(text: str) -> str:
    """Extract the first sentence from the Purpose section of an article."""
    # Find the Purpose section
    match = re.search(r"##\s*Purpose\s*\n+(.+?)(?:\n\n|\n##|\Z)", text, re.DOTALL)
    if not match:
        return ""
    paragraph = match.group(1).strip()
    # Take first sentence (ends with period, question mark, or exclamation)
    sentence_match = re.match(r"(.+?[.!?])(?:\s|$)", paragraph)
    if sentence_match:
        return sentence_match.group(1).strip()
    # No sentence-ending punctuation found — return whole first line
    return paragraph.split("\n")[0].strip()


def build_index(wiki_dir: Path, project_name: str) -> str:
    """Build INDEX.md content from all .md files in wiki_dir/modules/.

    Returns the full INDEX.md content as a string.
    Includes an Architecture section if architecture.md exists.
    """
    modules_dir = wiki_dir / "modules"
    architecture_path = wiki_dir / "architecture.md"

    has_modules = modules_dir.exists() and any(modules_dir.glob("*.md"))
    has_architecture = architecture_path.exists()

    if not has_modules and not has_architecture:
        return f"# Wiki Index — {project_name}\n\nNo modules found.\n"

    articles = sorted(modules_dir.glob("*.md")) if has_modules else []

    lines: list[str] = [
        f"# Wiki Index — {project_name}",
        "",
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Modules: {len(articles)}",
        "",
    ]

    # Architecture section
    if has_architecture:
        lines.append("## Architecture")
        lines.append("")
        lines.append("- [Architecture Overview](architecture.md)")
        lines.append("")

    # Modules section
    if articles:
        lines.append("## Modules")

        for article_path in articles:
            name = article_path.stem
            try:
                text = article_path.read_text(encoding="utf-8")
            except OSError:
                continue
            summary = _extract_purpose_first_sentence(text)
            rel_path = f"modules/{article_path.name}"
            if summary:
                lines.append(f"- [{name}]({rel_path}) — {summary}")
            else:
                lines.append(f"- [{name}]({rel_path})")
    elif not has_architecture:
        lines.append("## Modules")

    lines.append("")  # trailing newline
    return "\n".join(lines)


def write_index(wiki_dir: Path, project_name: str) -> None:
    """Build and write INDEX.md to wiki_dir."""
    content = build_index(wiki_dir, project_name)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "INDEX.md").write_text(content, encoding="utf-8")
