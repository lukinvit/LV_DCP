"""String-based template functions for Obsidian markdown pages.

No Jinja2 dependency — plain f-strings and str.join for all rendering.
"""

from __future__ import annotations


def _frontmatter(tags: list[str], **fields: str) -> str:
    """Build YAML frontmatter block."""
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {tag}")
    lines.append("---")
    return "\n".join(lines)


def render_home_page(
    *,
    project_name: str,
    languages: list[str],
    file_count: int,
    symbol_count: int,
    scan_date: str,
) -> str:
    """Render the project home page with stats and module links."""
    fm = _frontmatter(
        tags=["lvdcp", "project"],
        project=project_name,
        type="home",
        scan_date=scan_date,
    )
    lang_str = ", ".join(languages) if languages else "none"
    body = f"""# {project_name}

| Metric | Value |
|--------|-------|
| Files | {file_count} |
| Symbols | {symbol_count} |
| Languages | {lang_str} |
| Last scan | {scan_date} |

## Modules

See the [[Modules]] folder for per-module breakdowns.

## Navigation

- [[Recent Changes]]
- [[Tech Debt]]
"""
    return f"{fm}\n\n{body}"


def render_module_page(
    *,
    module_name: str,
    project_name: str,
    file_count: int,
    symbol_count: int,
    top_symbols: list[str],
    dependencies: list[str],
    dependents: list[str],
    scan_date: str,
) -> str:
    """Render a module page with stats, symbols, and wikilinks for deps."""
    fm = _frontmatter(
        tags=["lvdcp", "module"],
        project=project_name,
        module=module_name,
        type="module",
        scan_date=scan_date,
    )

    symbols_section = ""
    if top_symbols:
        items = "\n".join(f"- `{s}`" for s in top_symbols)
        symbols_section = f"\n## Top symbols\n\n{items}\n"

    deps_section = ""
    if dependencies:
        items = "\n".join(f"- [[{d}]]" for d in dependencies)
        deps_section = f"\n## Dependencies\n\n{items}\n"

    dependents_section = ""
    if dependents:
        items = "\n".join(f"- [[{d}]]" for d in dependents)
        dependents_section = f"\n## Dependents\n\n{items}\n"

    body = f"""# {module_name}

| Metric | Value |
|--------|-------|
| Files | {file_count} |
| Symbols | {symbol_count} |
| Project | [[{project_name}]] |
| Last scan | {scan_date} |
{symbols_section}{deps_section}{dependents_section}"""
    return f"{fm}\n\n{body}"


def render_recent_changes(
    *,
    project_name: str,
    changes: list[dict],
    scan_date: str,
) -> str:
    """Render a recent changes page.

    Each change dict is expected to have keys: file_path, churn_30d, last_author.
    """
    fm = _frontmatter(
        tags=["lvdcp", "changes"],
        project=project_name,
        type="recent_changes",
        scan_date=scan_date,
    )

    if not changes:
        table = "_No recent changes recorded._"
    else:
        rows = []
        for c in changes:
            fp = c.get("file_path", "")
            churn = c.get("churn_30d", 0)
            author = c.get("last_author", "")
            rows.append(f"| {fp} | {churn} | {author} |")
        table = (
            "| File | Churn (30d) | Last author |\n|------|-------------|-------------|\n"
            + "\n".join(rows)
        )

    body = f"""# Recent Changes — {project_name}

Last scan: {scan_date}

{table}
"""
    return f"{fm}\n\n{body}"


def render_tech_debt(
    *,
    project_name: str,
    hotspots: list[dict],
    scan_date: str,
) -> str:
    """Render a tech debt / hotspots page.

    Each hotspot dict is expected to have keys: file_path, churn_30d, commit_count.
    """
    fm = _frontmatter(
        tags=["lvdcp", "tech-debt"],
        project=project_name,
        type="tech_debt",
        scan_date=scan_date,
    )

    if not hotspots:
        table = "_No hotspots detected._"
    else:
        rows = []
        for h in hotspots:
            fp = h.get("file_path", "")
            churn = h.get("churn_30d", 0)
            commits = h.get("commit_count", 0)
            rows.append(f"| {fp} | {churn} | {commits} |")
        table = "| File | Churn (30d) | Commits |\n|------|-------------|--------|\n" + "\n".join(
            rows
        )

    body = f"""# Tech Debt — {project_name}

Last scan: {scan_date}

{table}
"""
    return f"{fm}\n\n{body}"
