"""Tests for advisory real-project eval helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from libs.core.projects_config import ProjectEntry

from tests.eval.real_project_eval import (
    LoadedProjectMap,
    RealProjectEvalReport,
    generate_real_project_report,
    load_project_name_map,
    run_real_project_eval,
)


class FakeIndex:
    def __init__(self, files_by_query: dict[str, list[str]]) -> None:
        self._files_by_query = files_by_query

    def __enter__(self) -> FakeIndex:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        return None

    def retrieve(self, query: str, *, mode: str = "navigate", limit: int = 5) -> SimpleNamespace:
        del mode
        files = self._files_by_query.get(query, [])
        return SimpleNamespace(files=files[:limit])


def _write_fixture(tmp_path: Path) -> Path:
    fixture_path = tmp_path / "fixture.yaml"
    fixture_path.write_text(
        "\n".join(
            [
                "version: 1",
                "projects:",
                "  GenericProject:",
                "    queries:",
                "      - id: q01",
                "        text: sample query",
                "        mode: navigate",
                "        expected:",
                "          files:",
                "            - src/app.py",
            ]
        ),
        encoding="utf-8",
    )
    return fixture_path


def test_load_project_name_map_reads_override_file(tmp_path: Path, monkeypatch: Any) -> None:
    map_path = tmp_path / "eval-project-map.yaml"
    map_path.write_text(
        "projects:\n  GoTS_Project: local-go-ts\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LVDCP_EVAL_PROJECT_MAP", str(map_path))

    loaded = load_project_name_map()

    assert loaded.exists is True
    assert loaded.path == map_path
    assert loaded.projects == {"GoTS_Project": "local-go-ts"}


def test_run_real_project_eval_records_skip_reason_for_unregistered_project(tmp_path: Path) -> None:
    fixture_path = _write_fixture(tmp_path)
    project_map = LoadedProjectMap(
        path=tmp_path / "missing-map.yaml",
        exists=False,
        projects={},
    )

    with patch("tests.eval.real_project_eval.list_projects", return_value=[]):
        report = run_real_project_eval(fixture_path, project_map=project_map)

    assert report.results == []
    assert report.skipped_projects == {"GenericProject": "not registered as 'GenericProject'"}


def test_run_real_project_eval_uses_project_map_and_computes_recall(tmp_path: Path) -> None:
    fixture_path = _write_fixture(tmp_path)
    real_root = tmp_path / "actual-project"
    real_root.mkdir()
    entry = ProjectEntry(
        root=real_root,
        registered_at_iso="2026-04-13T00:00:00Z",
    )
    project_map = LoadedProjectMap(
        path=tmp_path / "eval-project-map.yaml",
        exists=True,
        projects={"GenericProject": "actual-project"},
    )

    with (
        patch("tests.eval.real_project_eval.list_projects", return_value=[entry]),
        patch(
            "tests.eval.real_project_eval.ProjectIndex.open",
            return_value=FakeIndex({"sample query": ["src/app.py", "src/other.py"]}),
        ),
    ):
        report = run_real_project_eval(fixture_path, project_map=project_map)

    assert report.resolved_projects == {"GenericProject": "actual-project"}
    assert report.skipped_projects == {}
    assert report.per_project_recall == {"GenericProject": 1.0}
    assert report.overall_recall == 1.0
    assert len(report.results) == 1
    assert report.results[0].retrieved_files == ["src/app.py", "src/other.py"]


def test_generate_real_project_report_includes_mapping_and_skips(tmp_path: Path) -> None:
    report = RealProjectEvalReport(
        fixture_name="polyglot_queries.yaml",
        config_path=tmp_path / "config.yaml",
        project_map_path=tmp_path / "eval-project-map.yaml",
        project_map_exists=True,
        resolved_projects={"GoTS_Project": "my-local-gots"},
        skipped_projects={"PythonTS_Project": "not registered as 'my-local-pts'"},
    )

    md = generate_real_project_report(report, title="Polyglot Eval")

    assert "# Polyglot Eval" in md
    assert "Project map" in md
    assert "present" in md
    assert "Skipped projects" in md
    assert "PythonTS_Project" in md
