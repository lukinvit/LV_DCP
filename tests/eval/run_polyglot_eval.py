"""Polyglot eval runner — tests retrieval quality on real multi-language projects.

Loads polyglot_queries.yaml, maps generic project names to registered roots,
runs queries, and computes recall@5 per project and overall.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from libs.core.projects_config import list_projects
from libs.project_index.index import ProjectIndex, ProjectNotIndexedError

from tests.eval.metrics import recall_at_k

EVAL_DIR = Path(__file__).resolve().parent
POLYGLOT_YAML = EVAL_DIR / "polyglot_queries.yaml"

# Map generic eval project names → real project directory names on this machine.
# Values are local directory names; they never appear in eval output or reports.
PROJECT_NAME_MAP = {
    "GoTS_Project": "GoTS_Project",
    "PythonTS_Project": "PythonTS_Project",
}

DEFAULT_CONFIG_PATH = Path.home() / ".lvdcp" / "config.yaml"


@dataclass(frozen=True)
class PolyglotQueryResult:
    query_id: str
    project: str
    retrieved_files: list[str]
    expected_files: list[str]
    recall_5: float


@dataclass
class PolyglotReport:
    results: list[PolyglotQueryResult] = field(default_factory=list)
    per_project_recall: dict[str, float] = field(default_factory=dict)
    overall_recall: float = 0.0


def _find_project_root(project_dir_name: str) -> Path | None:
    """Find project root by directory name in registered projects."""
    for entry in list_projects(DEFAULT_CONFIG_PATH):
        if entry.root.name == project_dir_name:
            return entry.root
    return None


def run_polyglot_eval() -> PolyglotReport:
    """Run all polyglot queries and compute metrics."""
    data = yaml.safe_load(POLYGLOT_YAML.read_text(encoding="utf-8"))
    report = PolyglotReport()
    project_recalls: dict[str, list[float]] = {}

    for generic_name, project_data in data.get("projects", {}).items():
        real_name = PROJECT_NAME_MAP.get(generic_name)
        if not real_name:
            continue

        root = _find_project_root(real_name)
        if root is None:
            continue

        try:
            idx = ProjectIndex.open(root)
        except ProjectNotIndexedError:
            continue

        with idx:
            for q in project_data.get("queries", []):
                result = idx.retrieve(q["text"], mode=q["mode"], limit=5)
                expected = q.get("expected", {}).get("files", [])
                r5 = recall_at_k(result.files, expected, k=5) if expected else 1.0

                report.results.append(
                    PolyglotQueryResult(
                        query_id=q["id"],
                        project=generic_name,
                        retrieved_files=result.files[:5],
                        expected_files=expected,
                        recall_5=r5,
                    )
                )
                project_recalls.setdefault(generic_name, []).append(r5)

    # Aggregate
    for proj, recalls in project_recalls.items():
        report.per_project_recall[proj] = sum(recalls) / len(recalls) if recalls else 0.0

    all_recalls = [r.recall_5 for r in report.results]
    report.overall_recall = sum(all_recalls) / len(all_recalls) if all_recalls else 0.0

    return report
