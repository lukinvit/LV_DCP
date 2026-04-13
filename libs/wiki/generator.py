"""Claude subagent launcher for wiki article generation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_PROMPT_TEMPLATE = """\
You are updating the wiki article for module '{module_path}' in project '{project_name}'.

Current article (empty if first generation):
{existing_article}

Module files ({file_count} files):
{file_list}

Key symbols:
{symbols}

Dependencies (imports from):
{deps}

Dependents (imported by):
{dependents}

Write a concise wiki article (max {max_tokens} tokens) in this format:

# {module_path}

## Purpose
One paragraph: what this module does and why it exists.

## Key Components
Bullet list of main files/classes/functions with one-line descriptions.

## Dependencies
What this module depends on and why.

## Patterns & Decisions
Notable architectural patterns, design decisions, or conventions used.

## Known Issues
Any obvious tech debt, missing tests, or potential problems.

Rules:
- Be specific, reference actual file names and function names
- Update existing content incrementally, don't rewrite from scratch
- If the module is trivial (< 3 files), write 3-5 sentences total
- No generic filler text\
"""


def generate_wiki_article(  # noqa: PLR0913
    *,
    project_root: Path,
    project_name: str,
    module_path: str,
    file_list: list[str],
    symbols: list[str],
    deps: list[str],
    dependents: list[str],
    existing_article: str,
    max_tokens: int = 2000,
) -> str:
    """Generate a wiki article for a module using Claude CLI as subagent.

    Raises RuntimeError if the ``claude`` CLI is not found on PATH.
    """
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise RuntimeError(
            "Claude CLI ('claude') not found on PATH. "
            "Install it: npm install -g @anthropic-ai/claude-code"
        )

    prompt = _PROMPT_TEMPLATE.format(
        module_path=module_path,
        project_name=project_name,
        existing_article=existing_article or "(none — first generation)",
        file_count=len(file_list),
        file_list="\n".join(f"- {f}" for f in file_list),
        symbols="\n".join(f"- {s}" for s in symbols) if symbols else "(none)",
        deps="\n".join(f"- {d}" for d in deps) if deps else "(none)",
        dependents="\n".join(f"- {d}" for d in dependents) if dependents else "(none)",
        max_tokens=max_tokens,
    )

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
        timeout=60,
        cwd=str(project_root),
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI exited with code {result.returncode}: {result.stderr.strip()}"
        )

    return result.stdout.strip()


_ARCHITECTURE_PROMPT_TEMPLATE = """\
You are writing an Architecture overview page for the project '{project_name}'.

Modules and their purpose (from INDEX.md):
{module_list}

Top inter-module dependencies:
{dependency_list}

Write a concise architecture overview (max 3000 tokens) in this format:

# Architecture — {project_name}

## High-level Architecture
What kind of project this is, main layers, and how they relate.

## Data Flow
How data moves through the system — from input to output, through which layers.

## Key Integration Points
Where modules connect, what are the main interfaces and shared abstractions.

## Technology Stack Summary
Inferred from module names and patterns — languages, frameworks, key libraries.

Rules:
- Be specific, reference actual module names
- Focus on structure, not implementation details
- No generic filler text
- If only a few modules exist, keep it brief\
"""


def generate_architecture_article(
    *,
    project_root: Path,
    project_name: str,
    module_summaries: dict[str, str],
    top_dependencies: list[tuple[str, str]],
) -> str:
    """Generate an Architecture overview page using Claude CLI as subagent.

    Args:
        project_root: path to the project
        project_name: human-readable project name
        module_summaries: mapping of module_path -> one-sentence purpose
        top_dependencies: list of (source_module, target_module) pairs

    Raises RuntimeError if the ``claude`` CLI is not found on PATH.
    """
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise RuntimeError(
            "Claude CLI ('claude') not found on PATH. "
            "Install it: npm install -g @anthropic-ai/claude-code"
        )

    module_list = "\n".join(
        f"- {mod}: {summary}" if summary else f"- {mod}"
        for mod, summary in sorted(module_summaries.items())
    )
    dependency_list = (
        "\n".join(f"- {src} -> {dst}" for src, dst in top_dependencies[:20]) or "(none detected)"
    )

    prompt = _ARCHITECTURE_PROMPT_TEMPLATE.format(
        project_name=project_name,
        module_list=module_list or "(no modules yet)",
        dependency_list=dependency_list,
    )

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
        cwd=str(project_root),
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI exited with code {result.returncode}: {result.stderr.strip()}"
        )

    return result.stdout.strip()
