"""Markdown renderer for ResumePack — full and --inject modes."""

from __future__ import annotations

from datetime import UTC, datetime

from libs.breadcrumbs.views import ProjectResumePack, ResumePack

_INJECT_HARD_CAP_BYTES = 2048


def _humanize_age(ts: float) -> str:
    """Humanize time delta from timestamp to now.

    Args:
        ts: Unix timestamp.

    Returns:
        Human-readable age string (e.g., "5m ago", "2h ago").
    """
    delta = max(0, int(datetime.now(UTC).timestamp() - ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _render_activity_section(pack: ProjectResumePack, lines: list[str]) -> None:
    """Append activity and focus section to lines.

    Args:
        pack: ProjectResumePack instance.
        lines: List of markdown lines to append to.
    """
    if not pack.breadcrumbs_empty:
        last_age = _humanize_age(pack.recent_breadcrumbs[0].timestamp)
        sessions = len({bc.cc_session_id for bc in pack.recent_breadcrumbs if bc.cc_session_id})
        lines.append(
            f"**Last activity:** {last_age} · {sessions} sessions · "
            f"{len(pack.recent_breadcrumbs)} breadcrumbs in window"
        )
        lines.append("")
        lines.append("### What you were doing")
        if pack.inferred_focus.last_query:
            lines.append(f'Last query: "{pack.inferred_focus.last_query}"')
        if pack.inferred_focus.last_mode:
            lines.append(f"Last mode: {pack.inferred_focus.last_mode}")
        if pack.inferred_focus.hot_files:
            files_str = ", ".join(str(p) for p in pack.inferred_focus.hot_files[:5])
            lines.append(f"Hot files: {files_str}")
        lines.append("")
    else:
        lines.append("**Last activity:** none in window (breadcrumbs_empty)")
        lines.append("")


def _render_fs_section(pack: ProjectResumePack, lines: list[str]) -> None:
    """Append filesystem state section to lines.

    Args:
        pack: ProjectResumePack instance.
        lines: List of markdown lines to append to.
    """
    g = pack.snapshot.git
    lines.append("### Filesystem state")
    if g.branch:
        lines.append(f"- Branch: {g.branch}")
        if g.upstream:
            lines.append(f"- Upstream: {g.upstream} ({g.ahead} ahead, {g.behind} behind)")
        if g.dirty_files:
            sample = ", ".join(f.path for f in g.dirty_files[:5])
            lines.append(f"- Dirty: {len(g.dirty_files)} files ({sample})")
        if g.staged_files:
            lines.append(f"- Staged: {len(g.staged_files)} files")
        if g.last_commits:
            lines.append("- Last commits:")
            for c in g.last_commits[:3]:
                lines.append(f'  - {c.rel_time}: "{c.subject}"')
    else:
        lines.append("(not a git repo)")
    lines.append("")


def _render_plan_section(pack: ProjectResumePack, lines: list[str]) -> None:
    """Append active plan section to lines.

    Args:
        pack: ProjectResumePack instance.
        lines: List of markdown lines to append to.
    """
    if pack.snapshot.active_plan:
        plan = pack.snapshot.active_plan
        lines.append("### Active plan")
        lines.append(f"[{plan.path.name}]({plan.path}) — {plan.total_steps} steps")
        lines.append("")


def _render_questions_section(pack: ProjectResumePack, lines: list[str]) -> None:
    """Append open questions section to lines.

    Args:
        pack: ProjectResumePack instance.
        lines: List of markdown lines to append to.
    """
    if pack.open_questions:
        lines.append("### Open questions")
        for q in pack.open_questions:
            lines.append(f"- {q}")
        lines.append("")


def render_project_pack(pack: ProjectResumePack) -> str:
    """Render full project resume pack to markdown.

    Args:
        pack: ProjectResumePack instance.

    Returns:
        Markdown string with full project context.
    """
    g = pack.snapshot.git
    proj = pack.project_root.rsplit("/", 1)[-1] or pack.project_root
    header = f"## Resume: {proj} @ {g.branch or '(no git)'}"
    if g.upstream:
        header += f" ({g.ahead} ahead, {g.behind} behind)"
    lines: list[str] = [header, ""]

    _render_activity_section(pack, lines)
    _render_fs_section(pack, lines)
    _render_plan_section(pack, lines)
    _render_questions_section(pack, lines)

    return "\n".join(lines).rstrip() + "\n"


def render_inject(pack: ProjectResumePack) -> str:
    """Render compact project resume for SessionStart prepend (max 2KB).

    Args:
        pack: ProjectResumePack instance.

    Returns:
        Markdown string capped at 2048 bytes, or empty string if no context.
    """
    if pack.breadcrumbs_empty and not pack.snapshot.git.branch:
        return ""

    g = pack.snapshot.git
    proj = pack.project_root.rsplit("/", 1)[-1] or pack.project_root
    lines: list[str] = [f"## Resume: {proj} @ {g.branch or '(no git)'}", ""]

    if not pack.breadcrumbs_empty:
        if pack.inferred_focus.last_query:
            lines.append(f'Last query: "{pack.inferred_focus.last_query}"')
        if pack.inferred_focus.hot_files:
            files_str = ", ".join(str(p) for p in pack.inferred_focus.hot_files[:3])
            lines.append(f"Hot files: {files_str}")

    if g.branch and g.dirty_files:
        sample = ", ".join(f.path for f in g.dirty_files[:3])
        lines.append(f"Dirty: {len(g.dirty_files)} files ({sample})")

    md = "\n".join(lines).rstrip() + "\n"

    if len(md.encode("utf-8")) > _INJECT_HARD_CAP_BYTES:
        encoded = md.encode("utf-8")[: _INJECT_HARD_CAP_BYTES - 3] + b"..."
        return encoded.decode("utf-8", errors="ignore")

    return md


def render_cross_project(pack: ResumePack) -> str:
    """Render cross-project digest to markdown.

    Args:
        pack: ResumePack with cross_project scope.

    Returns:
        Markdown string listing recent projects and their activity.
    """
    if not pack.digest:
        return "## Resume: no recent activity in any project\n"

    lines = ["## Resume: cross-project digest", ""]
    for entry in pack.digest:
        age = _humanize_age(entry.last_ts)
        lines.append(f"- **{entry.project_root}** ({entry.count} events, last {age})")
        if entry.last_query:
            lines.append(f'  - last: "{entry.last_query}" [{entry.last_mode or "?"}]')

    return "\n".join(lines).rstrip() + "\n"
