"""ResumePack assemblers + FocusGuess synthesis."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from libs.breadcrumbs.models import BreadcrumbView
from libs.breadcrumbs.reader import ProjectDigestEntry, load_cross_project, load_recent
from libs.breadcrumbs.snapshot import A1Snapshot, build_a1_snapshot
from libs.breadcrumbs.store import BreadcrumbStore


@dataclass(frozen=True)
class FocusGuess:
    """Synthesized focus from recent breadcrumbs."""

    last_query: str | None
    last_mode: Literal["navigate", "edit"] | None
    hot_files: list[Path]
    hot_symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectResumePack:
    """Single-project context digest."""

    project_root: str
    snapshot: A1Snapshot
    recent_breadcrumbs: list[BreadcrumbView]
    inferred_focus: FocusGuess
    open_questions: list[str]
    breadcrumbs_empty: bool
    scope: Literal["project"] = "project"


@dataclass(frozen=True)
class ResumePack:
    """Cross-project or single-project resume digest."""

    generated_at: datetime
    scope: Literal["project", "cross_project"]
    project_pack: ProjectResumePack | None
    digest: list[ProjectDigestEntry] | None


def _synthesize_focus(breadcrumbs: list[BreadcrumbView]) -> FocusGuess:
    """Synthesize FocusGuess from recent breadcrumbs.

    Args:
        breadcrumbs: BreadcrumbView list ordered DESC by timestamp.

    Returns:
        FocusGuess with last query, mode, and hot files ranked by frequency.
    """
    if not breadcrumbs:
        return FocusGuess(last_query=None, last_mode=None, hot_files=[])

    most_recent = breadcrumbs[0]
    counter: Counter[str] = Counter()
    for bc in breadcrumbs:
        for p in bc.paths_touched:
            counter[p] += 1
    hot = [Path(p) for p, _ in counter.most_common(5)]

    mode: Literal["navigate", "edit"] | None = None
    if most_recent.mode == "navigate":
        mode = "navigate"
    elif most_recent.mode == "edit":
        mode = "edit"

    return FocusGuess(
        last_query=most_recent.query,
        last_mode=mode,
        hot_files=hot,
    )


def _open_questions_from(breadcrumbs: list[BreadcrumbView]) -> list[str]:
    """Extract open questions from breadcrumbs (failed steps, errors).

    Args:
        breadcrumbs: BreadcrumbView list.

    Returns:
        List of up to 5 question summaries, capped at 200 chars each.
    """
    questions: list[str] = []
    for bc in breadcrumbs:
        if bc.turn_summary and (
            "error" in bc.turn_summary.lower()
            or "fail" in bc.turn_summary.lower()
        ):
            questions.append(bc.turn_summary[:200])
    return questions[:5]


def build_project_resume_pack(  # noqa: PLR0913
    *,
    store: BreadcrumbStore,
    project_root: Path,
    os_user: str,
    cc_account_email: str | None,
    since_ts: float,
    limit: int,
) -> ProjectResumePack:
    """Build a single-project resume pack.

    Args:
        store: BreadcrumbStore instance.
        project_root: Path to project root.
        os_user: OS username to filter by.
        cc_account_email: Optional Claude account email filter.
        since_ts: Timestamp cutoff.
        limit: Max breadcrumbs to load.

    Returns:
        ProjectResumePack with snapshot, recent breadcrumbs, and inferred focus.
    """
    breadcrumbs = load_recent(
        store=store,
        project_root=str(project_root),
        os_user=os_user,
        since_ts=since_ts,
        limit=limit,
        cc_account_email=cc_account_email,
    )
    return ProjectResumePack(
        project_root=str(project_root),
        snapshot=build_a1_snapshot(project_root=project_root),
        recent_breadcrumbs=breadcrumbs,
        inferred_focus=_synthesize_focus(breadcrumbs),
        open_questions=_open_questions_from(breadcrumbs),
        breadcrumbs_empty=not breadcrumbs,
    )


def build_cross_project_resume_pack(
    *,
    store: BreadcrumbStore,
    os_user: str,
    since_ts: float,
    limit: int,
) -> ResumePack:
    """Build a cross-project resume digest.

    Args:
        store: BreadcrumbStore instance.
        os_user: OS username to filter by.
        since_ts: Timestamp cutoff.
        limit: Max projects to return.

    Returns:
        ResumePack with cross_project scope and per-project digest.
    """
    digest = load_cross_project(
        store=store, os_user=os_user, since_ts=since_ts, limit=limit
    )
    return ResumePack(
        generated_at=datetime.now(UTC),
        scope="cross_project",
        project_pack=None,
        digest=digest,
    )
