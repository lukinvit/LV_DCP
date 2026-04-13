"""Tests for cross-project pattern detection."""

from __future__ import annotations

from libs.patterns.detector import (
    detect_dependency_patterns,
    detect_structural_patterns,
)

# ---------------------------------------------------------------------------
# detect_dependency_patterns
# ---------------------------------------------------------------------------


class TestDetectDependencyPatterns:
    def test_finds_common_deps(self) -> None:
        project_deps = {
            "alpha": ["fastapi", "pydantic", "sqlalchemy"],
            "beta": ["fastapi", "pydantic", "requests"],
            "gamma": ["fastapi", "pydantic", "httpx"],
        }
        patterns = detect_dependency_patterns(project_deps)

        names = {p.name for p in patterns}
        assert "fastapi" in names
        assert "pydantic" in names

    def test_confidence_value(self) -> None:
        project_deps = {
            "alpha": ["fastapi", "pydantic"],
            "beta": ["fastapi", "requests"],
            "gamma": ["fastapi", "httpx"],
        }
        patterns = detect_dependency_patterns(project_deps)
        fastapi = next(p for p in patterns if p.name == "fastapi")
        assert fastapi.confidence == 1.0  # 3/3

    def test_correct_projects_list(self) -> None:
        project_deps = {
            "alpha": ["fastapi", "pydantic"],
            "beta": ["fastapi"],
            "gamma": ["pydantic"],
        }
        patterns = detect_dependency_patterns(project_deps)
        fastapi = next(p for p in patterns if p.name == "fastapi")
        assert fastapi.projects == ("alpha", "beta")
        assert fastapi.pattern_type == "dependency"

    def test_no_patterns_below_threshold(self) -> None:
        project_deps = {
            "alpha": ["fastapi"],
            "beta": ["requests"],
            "gamma": ["httpx"],
        }
        patterns = detect_dependency_patterns(project_deps)
        assert patterns == []

    def test_custom_min_projects(self) -> None:
        project_deps = {
            "a": ["fastapi"],
            "b": ["fastapi"],
            "c": ["fastapi"],
            "d": ["requests"],
            "e": ["requests"],
        }
        patterns = detect_dependency_patterns(project_deps, min_projects=3)
        names = {p.name for p in patterns}
        assert "fastapi" in names
        assert "requests" not in names

    def test_empty_input(self) -> None:
        assert detect_dependency_patterns({}) == []


# ---------------------------------------------------------------------------
# detect_structural_patterns
# ---------------------------------------------------------------------------


class TestDetectStructuralPatterns:
    def test_finds_common_dirs(self) -> None:
        project_dirs = {
            "alpha": ["src/models", "src/routes", "src/utils"],
            "beta": ["app/models", "app/routes"],
            "gamma": ["lib/models"],
        }
        patterns = detect_structural_patterns(project_dirs)

        names = {p.name for p in patterns}
        assert "models" in names
        assert "routes" in names

    def test_correct_projects_list(self) -> None:
        project_dirs = {
            "alpha": ["src/models"],
            "beta": ["app/models"],
            "gamma": ["lib/services"],
        }
        patterns = detect_structural_patterns(project_dirs)
        models = next(p for p in patterns if p.name == "models")
        assert models.projects == ("alpha", "beta")
        assert models.pattern_type == "structural"

    def test_no_patterns_below_threshold(self) -> None:
        project_dirs = {
            "alpha": ["src/models"],
            "beta": ["app/routes"],
            "gamma": ["lib/services"],
        }
        patterns = detect_structural_patterns(project_dirs)
        assert patterns == []

    def test_deduplicates_leaves_within_project(self) -> None:
        """Same leaf appearing twice in one project should count only once."""
        project_dirs = {
            "alpha": ["src/models", "tests/models"],
            "beta": ["app/routes"],
        }
        patterns = detect_structural_patterns(project_dirs)
        # "models" only in alpha => below threshold of 2
        assert all(p.name != "models" for p in patterns)

    def test_empty_input(self) -> None:
        assert detect_structural_patterns({}) == []
