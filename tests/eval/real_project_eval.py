"""Shared helpers for advisory eval on real, locally registered projects."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from libs.core.projects_config import list_projects
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError

from tests.eval.metrics import recall_at_k

EVAL_PROJECT_MAP_ENV = "LVDCP_EVAL_PROJECT_MAP"
DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"
DEFAULT_PROJECT_MAP_PATH = Path.home() / ".lvdcp" / "eval-project-map.yaml"


@dataclass(frozen=True)
class LoadedProjectMap:
    path: Path
    exists: bool
    projects: dict[str, str]


@dataclass(frozen=True)
class RealProjectEvalQueryResult:
    query_id: str
    project: str
    retrieved_files: list[str]
    expected_files: list[str]
    recall_5: float


@dataclass
class RealProjectEvalReport:
    fixture_name: str
    config_path: Path
    project_map_path: Path
    project_map_exists: bool
    resolved_projects: dict[str, str] = field(default_factory=dict)
    skipped_projects: dict[str, str] = field(default_factory=dict)
    results: list[RealProjectEvalQueryResult] = field(default_factory=list)
    per_project_recall: dict[str, float] = field(default_factory=dict)
    overall_recall: float = 0.0


def _default_project_map_path() -> Path:
    env_value = os.environ.get(EVAL_PROJECT_MAP_ENV)
    if env_value:
        return Path(env_value).expanduser()
    return DEFAULT_PROJECT_MAP_PATH


def load_project_name_map(path: Path | None = None) -> LoadedProjectMap:
    """Load optional generic-name -> local-directory-name mapping."""
    resolved_path = (path or _default_project_map_path()).expanduser()
    if not resolved_path.exists():
        return LoadedProjectMap(path=resolved_path, exists=False, projects={})

    data_obj = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    if data_obj is None:
        return LoadedProjectMap(path=resolved_path, exists=True, projects={})
    if not isinstance(data_obj, dict):
        msg = f"project map at {resolved_path} must be a mapping"
        raise ValueError(msg)

    projects_obj = data_obj.get("projects", {})
    if not isinstance(projects_obj, dict):
        msg = f"project map at {resolved_path} must contain a 'projects' mapping"
        raise ValueError(msg)

    projects: dict[str, str] = {}
    for generic_name_obj, local_name_obj in projects_obj.items():
        if not isinstance(generic_name_obj, str) or not isinstance(local_name_obj, str):
            msg = f"project map at {resolved_path} must use string keys and values"
            raise ValueError(msg)
        projects[generic_name_obj] = local_name_obj

    return LoadedProjectMap(path=resolved_path, exists=True, projects=projects)


def _load_fixture_queries(fixture_path: Path) -> dict[str, list[dict[str, object]]]:
    data_obj = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(data_obj, dict):
        msg = f"fixture at {fixture_path} must be a mapping"
        raise ValueError(msg)

    projects_obj = data_obj.get("projects", {})
    if not isinstance(projects_obj, dict):
        msg = f"fixture at {fixture_path} must contain a 'projects' mapping"
        raise ValueError(msg)

    projects: dict[str, list[dict[str, object]]] = {}
    for generic_name_obj, project_data_obj in projects_obj.items():
        if not isinstance(generic_name_obj, str) or not isinstance(project_data_obj, dict):
            msg = f"fixture at {fixture_path} has invalid project entry"
            raise ValueError(msg)
        queries_obj = project_data_obj.get("queries", [])
        if not isinstance(queries_obj, list):
            msg = f"fixture at {fixture_path} has invalid queries for {generic_name_obj}"
            raise ValueError(msg)

        queries: list[dict[str, object]] = []
        for query_obj in queries_obj:
            if not isinstance(query_obj, dict):
                msg = f"fixture at {fixture_path} has non-mapping query for {generic_name_obj}"
                raise ValueError(msg)
            queries.append(query_obj)
        projects[generic_name_obj] = queries

    return projects


def _require_str(query: Mapping[str, object], key: str, *, fixture_name: str, project: str) -> str:
    value = query.get(key)
    if isinstance(value, str):
        return value
    msg = f"{fixture_name}: query in {project!r} is missing string field {key!r}"
    raise ValueError(msg)


def _expected_files(query: Mapping[str, object]) -> list[str]:
    expected_obj = query.get("expected", {})
    if not isinstance(expected_obj, dict):
        return []

    files_obj = expected_obj.get("files", [])
    if not isinstance(files_obj, list):
        return []

    files: list[str] = []
    for file_obj in files_obj:
        if isinstance(file_obj, str):
            files.append(file_obj)
    return files


def run_real_project_eval(
    fixture_path: Path,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    project_map: LoadedProjectMap | None = None,
    limit: int = 5,
) -> RealProjectEvalReport:
    """Run advisory eval against locally registered real projects."""
    loaded_map = project_map or load_project_name_map()
    report = RealProjectEvalReport(
        fixture_name=fixture_path.name,
        config_path=config_path,
        project_map_path=loaded_map.path,
        project_map_exists=loaded_map.exists,
    )
    registered_roots = {entry.root.name: entry.root for entry in list_projects(config_path)}

    for generic_name, queries in _load_fixture_queries(fixture_path).items():
        resolved_name = loaded_map.projects.get(generic_name, generic_name)
        report.resolved_projects[generic_name] = resolved_name

        root = registered_roots.get(resolved_name)
        if root is None:
            report.skipped_projects[generic_name] = f"not registered as '{resolved_name}'"
            continue

        try:
            idx = ProjectIndex.open(root)
        except ProjectNotIndexedError:
            report.skipped_projects[generic_name] = f"registered at '{root}' but not indexed"
            continue

        with idx:
            project_recalls: list[float] = []
            for query in queries:
                query_id = _require_str(
                    query,
                    "id",
                    fixture_name=fixture_path.name,
                    project=generic_name,
                )
                query_text = _require_str(
                    query,
                    "text",
                    fixture_name=fixture_path.name,
                    project=generic_name,
                )
                mode = _require_str(
                    query,
                    "mode",
                    fixture_name=fixture_path.name,
                    project=generic_name,
                )
                expected = _expected_files(query)
                result = idx.retrieve(query_text, mode=mode, limit=limit)
                recall = recall_at_k(result.files, expected, k=limit) if expected else 1.0

                report.results.append(
                    RealProjectEvalQueryResult(
                        query_id=query_id,
                        project=generic_name,
                        retrieved_files=result.files[:limit],
                        expected_files=expected,
                        recall_5=recall,
                    )
                )
                project_recalls.append(recall)

            if project_recalls:
                report.per_project_recall[generic_name] = sum(project_recalls) / len(
                    project_recalls
                )

    recalls = [result.recall_5 for result in report.results]
    report.overall_recall = sum(recalls) / len(recalls) if recalls else 0.0
    return report


def skip_summary(report: RealProjectEvalReport) -> str:
    if not report.skipped_projects:
        return "no skipped projects"
    return "; ".join(
        f"{project}: {reason}" for project, reason in sorted(report.skipped_projects.items())
    )


def generate_real_project_report(report: RealProjectEvalReport, *, title: str) -> str:
    """Render a markdown report for an advisory real-project eval run."""
    lines = [f"# {title}", "", "## Environment", ""]
    lines.append(f"- Config path: `{report.config_path}`")
    map_state = "present" if report.project_map_exists else "missing; identity mapping used"
    lines.append(f"- Project map: `{report.project_map_path}` ({map_state})")
    lines.append(f"- Overall recall@5: **{report.overall_recall:.3f}**")
    lines.append("")

    if report.skipped_projects:
        lines.extend(["## Skipped projects", ""])
        for project, reason in sorted(report.skipped_projects.items()):
            resolved = report.resolved_projects.get(project, project)
            if resolved == project:
                lines.append(f"- `{project}` — {reason}")
            else:
                lines.append(f"- `{project}` → `{resolved}` — {reason}")
        lines.append("")

    if not report.results:
        lines.extend(["## No evaluated projects", "", "All advisory projects were skipped."])
        return "\n".join(lines)

    grouped: dict[str, list[RealProjectEvalQueryResult]] = defaultdict(list)
    for result in report.results:
        grouped[result.project].append(result)

    lines.extend(["## Per-project results", ""])
    for project in sorted(grouped):
        resolved = report.resolved_projects.get(project, project)
        heading = (
            f"### {project}"
            if resolved == project
            else f"### {project} (registered as `{resolved}`)"
        )
        lines.extend([heading, ""])
        lines.append("| id | recall@5 | missed |")
        lines.append("|---|---|---|")
        for result in grouped[project]:
            missed = [
                path for path in result.expected_files if path not in result.retrieved_files[:5]
            ]
            missed_str = ", ".join(missed) if missed else "—"
            lines.append(f"| {result.query_id} | {result.recall_5:.2f} | {missed_str} |")
        avg = report.per_project_recall.get(project, 0.0)
        lines.extend(["", f"**Average recall@5: {avg:.3f}**", ""])

    return "\n".join(lines)
