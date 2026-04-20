"""Build NAVIGATE and EDIT context packs from retrieval results.

These are deterministic in Phase 1 — no LLM summarization. Just structured
markdown with the top files, symbols, and for EDIT mode a tests/configs split.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from libs.core.entities import ContextPack, PackMode
from libs.core.paths import is_test_path
from libs.retrieval.disambiguate import format_suggestion_hint, suggest_disambiguators
from libs.retrieval.pipeline import RetrievalResult

PIPELINE_VERSION = "phase-2-v0"

# Base score for git-changed files injected into edit packs.
_GIT_CHANGED_SCORE = 3.0


def _git_changed_files(project_root: Path) -> list[str]:
    """Return files with uncommitted changes (staged + unstaged).

    Falls back to an empty list when the directory is not a git repo,
    git is not installed, or the command times out.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],  # noqa: S607
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def build_navigate_pack(
    *,
    project_slug: str,
    query: str,
    result: RetrievalResult,
) -> ContextPack:
    lines: list[str] = []
    lines.append("# Context pack — navigate")
    lines.append("")
    lines.append(f"**Project:** `{project_slug}`")
    lines.append(f"**Query:** {query}")
    lines.append(f"**Coverage:** {result.coverage}")
    lines.append(f"**Pipeline:** `{PIPELINE_VERSION}`")
    lines.append("")

    if result.coverage == "ambiguous":
        lines.append(
            "> ⚠ **Ambiguous coverage** — many files scored similarly. "
            "Consider re-querying with more specific keywords or expanding `--limit`."
        )
        suggestions = suggest_disambiguators(query, list(result.files))
        hint = format_suggestion_hint(suggestions)
        if hint:
            lines.append(f"> {hint}")
        lines.append("")

    lines.append("## Top files")
    lines.append("")
    if not result.files:
        lines.append("_no files retrieved_")
    else:
        for i, path in enumerate(result.files, start=1):
            score = result.scores.get(path, 0.0)
            lines.append(f"{i}. `{path}` (score {score:.2f})")
    lines.append("")

    lines.append("## Top symbols")
    lines.append("")
    if not result.symbols:
        lines.append("_no symbols retrieved_")
    else:
        for i, fq in enumerate(result.symbols, start=1):
            lines.append(f"{i}. `{fq}`")
    lines.append("")

    md = "\n".join(lines)
    return ContextPack(
        project_slug=project_slug,
        query=query,
        mode=PackMode.NAVIGATE,
        assembled_markdown=md,
        size_bytes=len(md.encode("utf-8")),
        retrieved_files=tuple(result.files),
        retrieved_symbols=tuple(result.symbols),
        pipeline_version=PIPELINE_VERSION,
        trace_id=result.trace.trace_id,
        coverage=result.coverage,
    )


def build_edit_pack(  # noqa: PLR0912, PLR0915
    *,
    project_slug: str,
    query: str,
    result: RetrievalResult,
    project_root: Path | None = None,
) -> ContextPack:
    # Detect uncommitted git changes and merge them into retrieval results.
    git_changed: list[str] = []
    if project_root is not None:
        git_changed = _git_changed_files(project_root)
        for path in git_changed:
            if path not in result.files:
                result.files.append(path)
            # Boost score so changed files rank high in the pack.
            result.scores.setdefault(path, _GIT_CHANGED_SCORE)

    # Split retrieved files into categories by path heuristics
    target_files: list[str] = []
    impacted_tests: list[str] = []
    impacted_configs: list[str] = []
    for p in result.files:
        if is_test_path(p):
            impacted_tests.append(p)
        elif p.endswith((".yaml", ".yml", ".json", ".toml")) or "/config/" in p:
            impacted_configs.append(p)
        else:
            target_files.append(p)

    lines: list[str] = []
    lines.append("# Context pack — edit")
    lines.append("")
    lines.append(f"**Project:** `{project_slug}`")
    lines.append(f"**Intent:** {query}")
    lines.append(f"**Coverage:** {result.coverage}")
    lines.append(f"**Pipeline:** `{PIPELINE_VERSION}`")
    lines.append("")

    if result.coverage == "ambiguous":
        lines.append(
            "> ⚠ **Ambiguous coverage on an edit task.** Do not proceed with "
            "these results alone. Re-query with more specific keywords, expand "
            "`--limit`, or ask the user for clarification before making changes."
        )
        suggestions = suggest_disambiguators(query, list(result.files))
        hint = format_suggestion_hint(suggestions)
        if hint:
            lines.append(f"> {hint}")
        lines.append("")
    else:
        lines.append(
            "> This is an **edit pack**: files grouped by role so the executor can "
            "plan a minimal, reversible patch. Run validation after every change."
        )
        lines.append("")

    if git_changed:
        lines.append("## Currently modified (uncommitted)")
        lines.append("")
        for p in git_changed:
            lines.append(f"- `{p}`")
        lines.append("")

    lines.append("## Target files")
    lines.append("")
    if not target_files:
        lines.append("_no target files identified — re-query with more specific intent_")
    for p in target_files:
        score = result.scores.get(p, 0.0)
        lines.append(f"- `{p}` (score {score:.2f})")
    lines.append("")

    lines.append("## Impacted tests")
    lines.append("")
    if not impacted_tests:
        lines.append("_no tests directly matched — verify that target files are test-covered_")
    for p in impacted_tests:
        lines.append(f"- `{p}`")
    lines.append("")

    lines.append("## Impacted configs")
    lines.append("")
    if not impacted_configs:
        lines.append("_no config files matched_")
    for p in impacted_configs:
        lines.append(f"- `{p}`")
    lines.append("")

    lines.append("## Candidate symbols")
    lines.append("")
    if not result.symbols:
        lines.append("_no symbol candidates_")
    for fq in result.symbols:
        lines.append(f"- `{fq}`")
    lines.append("")

    lines.append("## Reminder: edit discipline (constitution §II.10)")
    lines.append("")
    lines.append("1. Build minimal plan before patching multiple files")
    lines.append(
        "2. Never touch write_protected_paths (generated, vendor, dist, applied migrations)"
    )
    lines.append("3. Run lint + typecheck + tests after every change")
    lines.append("4. Summarize the diff when done")

    md = "\n".join(lines)
    return ContextPack(
        project_slug=project_slug,
        query=query,
        mode=PackMode.EDIT,
        assembled_markdown=md,
        size_bytes=len(md.encode("utf-8")),
        retrieved_files=tuple(result.files),
        retrieved_symbols=tuple(result.symbols),
        pipeline_version=PIPELINE_VERSION,
        trace_id=result.trace.trace_id,
        coverage=result.coverage,
    )
