"""Detect patterns shared across multiple indexed projects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal


@dataclass(frozen=True)
class PatternEntry:
    """A single cross-project pattern."""

    name: str
    pattern_type: Literal["dependency", "structural"]
    projects: tuple[str, ...]
    confidence: float  # projects_with / total


def detect_dependency_patterns(
    project_deps: dict[str, list[str]],
    *,
    min_projects: int = 2,
) -> list[PatternEntry]:
    """Count dependencies across projects; return those in >= *min_projects*.

    Args:
        project_deps: mapping ``{project_name: [dep, ...]}``
        min_projects: minimum number of projects a dep must appear in

    Returns:
        List of :class:`PatternEntry` sorted by confidence descending,
        then by name ascending.
    """
    total = len(project_deps)
    if total == 0:
        return []

    dep_to_projects: dict[str, list[str]] = {}
    for project, deps in project_deps.items():
        for dep in deps:
            dep_to_projects.setdefault(dep, []).append(project)

    results: list[PatternEntry] = []
    for dep, projects in dep_to_projects.items():
        if len(projects) >= min_projects:
            results.append(
                PatternEntry(
                    name=dep,
                    pattern_type="dependency",
                    projects=tuple(sorted(projects)),
                    confidence=len(projects) / total,
                )
            )

    results.sort(key=lambda e: (-e.confidence, e.name))
    return results


def detect_structural_patterns(
    project_dirs: dict[str, list[str]],
    *,
    min_projects: int = 2,
) -> list[PatternEntry]:
    """Normalise directory names to leaf segments, count across projects.

    Args:
        project_dirs: mapping ``{project_name: [dir_path, ...]}``
        min_projects: minimum number of projects a leaf must appear in

    Returns:
        List of :class:`PatternEntry` sorted by confidence descending,
        then by name ascending.
    """
    total = len(project_dirs)
    if total == 0:
        return []

    leaf_to_projects: dict[str, list[str]] = {}
    for project, dirs in project_dirs.items():
        seen_leaves: set[str] = set()
        for d in dirs:
            leaf = PurePosixPath(d).name
            if leaf and leaf not in seen_leaves:
                seen_leaves.add(leaf)
                leaf_to_projects.setdefault(leaf, []).append(project)

    results: list[PatternEntry] = []
    for leaf, projects in leaf_to_projects.items():
        if len(projects) >= min_projects:
            results.append(
                PatternEntry(
                    name=leaf,
                    pattern_type="structural",
                    projects=tuple(sorted(projects)),
                    confidence=len(projects) / total,
                )
            )

    results.sort(key=lambda e: (-e.confidence, e.name))
    return results
