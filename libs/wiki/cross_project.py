"""Cross-project wiki: global INDEX and pattern detection across projects."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from libs.core.projects_config import list_projects


def _collect_project_indexes(config_path: Path) -> dict[str, str]:
    """Read INDEX.md from each registered project.

    Returns mapping of project_name -> INDEX.md content.
    """
    projects = list_projects(config_path)
    indexes: dict[str, str] = {}
    for proj in projects:
        index_path = proj.root / ".context" / "wiki" / "INDEX.md"
        if index_path.exists():
            try:
                indexes[proj.root.name] = index_path.read_text(encoding="utf-8")
            except OSError:
                continue
    return indexes


def _build_global_index(project_indexes: dict[str, str]) -> str:
    """Build a global INDEX.md aggregating all project indexes."""
    lines: list[str] = [
        "# Global Wiki Index",
        "",
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Projects: {len(project_indexes)}",
        "",
    ]

    for project_name in sorted(project_indexes):
        lines.append(f"## {project_name}")
        lines.append("")
        # Extract module lines from the project index
        in_modules = False
        for line in project_indexes[project_name].splitlines():
            if line.startswith("## Modules"):
                in_modules = True
                continue
            if line.startswith("## ") and in_modules:
                break
            if in_modules and line.startswith("- ["):
                lines.append(line)
        lines.append("")

    lines.append("")
    return "\n".join(lines)


def _detect_patterns_via_claude(
    project_indexes: dict[str, str],
    wiki_dir: Path,
) -> int:
    """Use Claude CLI to detect cross-project patterns.

    Returns number of pattern files written.
    """
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise RuntimeError(
            "Claude CLI ('claude') not found on PATH. "
            "Install it: npm install -g @anthropic-ai/claude-code"
        )

    # Build combined context
    parts: list[str] = []
    for name, content in sorted(project_indexes.items()):
        parts.append(f"### Project: {name}\n\n{content}")
    combined = "\n\n---\n\n".join(parts)

    prompt = f"""\
You are analyzing wiki indexes from multiple projects to find cross-project patterns.

{combined}

Identify patterns across these projects:
1. Shared dependencies (modules with similar names or purposes)
2. Common architectural patterns (similar module structures)
3. Shared technology stack elements

For EACH pattern found, output a section like:

## Pattern: <pattern-name>

<2-4 sentences describing the pattern, which projects exhibit it, and why it matters.>

Projects: <comma-separated list of project names>

If fewer than 2 projects are provided, or no meaningful patterns exist, output:

## No patterns detected

Only {len(project_indexes)} project(s) indexed — need at least 2 for cross-project analysis.

Rules:
- Be specific, reference actual module names from the indexes
- Maximum 5 patterns
- No generic filler\
"""

    result = subprocess.run(  # noqa: S603
        [
            claude_bin,
            "-p",
            "--output-format",
            "text",
            "--max-turns",
            "3",
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI exited with code {result.returncode}: {result.stderr.strip()}"
        )

    output = result.stdout.strip()
    patterns_dir = wiki_dir / "patterns"
    patterns_dir.mkdir(parents=True, exist_ok=True)

    # Parse output into separate pattern files
    count = 0
    current_name: str | None = None
    current_lines: list[str] = []

    for line in output.splitlines():
        if line.startswith("## Pattern: "):
            # Save previous pattern
            if current_name and current_lines:
                safe_name = current_name.lower().replace(" ", "-").replace("/", "-")
                (patterns_dir / f"{safe_name}.md").write_text(
                    "\n".join(current_lines), encoding="utf-8"
                )
                count += 1
            current_name = line[len("## Pattern: ") :].strip()
            current_lines = [line]
        elif current_name is not None:
            current_lines.append(line)

    # Save last pattern
    if current_name and current_lines:
        safe_name = current_name.lower().replace(" ", "-").replace("/", "-")
        (patterns_dir / f"{safe_name}.md").write_text("\n".join(current_lines), encoding="utf-8")
        count += 1

    return count


def generate_cross_project_wiki(config_path: Path, wiki_dir: Path) -> int:
    """Generate cross-project wiki from all registered projects.

    1. Reads all registered projects from config
    2. For each project: reads its .context/wiki/INDEX.md
    3. Builds a global INDEX at wiki_dir/INDEX.md
    4. Detects common patterns via Claude CLI
    5. Writes pattern articles to wiki_dir/patterns/

    Returns number of pattern articles written.
    """
    wiki_dir.mkdir(parents=True, exist_ok=True)

    project_indexes = _collect_project_indexes(config_path)
    if not project_indexes:
        (wiki_dir / "INDEX.md").write_text(
            "# Global Wiki Index\n\nNo projects with wiki indexes found.\n",
            encoding="utf-8",
        )
        return 0

    # Write global INDEX
    global_index = _build_global_index(project_indexes)
    (wiki_dir / "INDEX.md").write_text(global_index, encoding="utf-8")

    # Detect patterns
    try:
        return _detect_patterns_via_claude(project_indexes, wiki_dir)
    except RuntimeError:
        # Claude CLI not available — still wrote the global index
        return 0
