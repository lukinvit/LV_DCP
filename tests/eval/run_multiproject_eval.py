"""Advisory multi-project eval runner for real locally registered projects."""

from __future__ import annotations

from pathlib import Path

from tests.eval.real_project_eval import (
    DEFAULT_CONFIG_PATH,
    LoadedProjectMap,
    RealProjectEvalQueryResult,
    RealProjectEvalReport,
    load_project_name_map,
    run_real_project_eval,
)

EVAL_DIR = Path(__file__).resolve().parent
MULTIPROJECT_YAML = EVAL_DIR / "multiproject_queries.yaml"

MultiprojectQueryResult = RealProjectEvalQueryResult
MultiprojectReport = RealProjectEvalReport


def run_multiproject_eval(project_map: LoadedProjectMap | None = None) -> MultiprojectReport:
    """Run advisory multi-project eval against locally registered projects."""
    return run_real_project_eval(
        MULTIPROJECT_YAML,
        config_path=DEFAULT_CONFIG_PATH,
        project_map=project_map or load_project_name_map(),
    )
