"""Tests for role-weighted score fusion (D1), config boost (D2), graph depth (D3)."""

from __future__ import annotations

from libs.retrieval.pipeline import (
    CONFIG_BOOST_BASELINE,
    CONFIG_TRIGGER_KEYWORDS,
    DOCS_OVERRIDE_KEYWORDS,
    DOCS_OVERRIDE_MULTIPLIER,
    ROLE_WEIGHTS_EDIT,
    ROLE_WEIGHTS_NAVIGATE,
    _apply_role_weights,
    _maybe_boost_config_files,
)


class TestRoleWeightedFusion:
    """D1: role-weighted score fusion."""

    def test_demote_docs_in_navigate_mode(self) -> None:
        file_scores = {
            "libs/retrieval/pipeline.py": 5.0,
            "docs/superpowers/specs/design.md": 5.0,
        }
        file_roles = {
            "libs/retrieval/pipeline.py": "source",
            "docs/superpowers/specs/design.md": "docs",
        }
        _apply_role_weights(file_scores, file_roles, "how does retrieval work", "navigate")
        assert (
            file_scores["libs/retrieval/pipeline.py"]
            > file_scores["docs/superpowers/specs/design.md"]
        )
        assert file_scores["libs/retrieval/pipeline.py"] == 5.0 * ROLE_WEIGHTS_NAVIGATE["source"]
        assert (
            file_scores["docs/superpowers/specs/design.md"] == 5.0 * ROLE_WEIGHTS_NAVIGATE["docs"]
        )

    def test_demote_docs_in_edit_mode(self) -> None:
        file_scores = {
            "libs/retrieval/pipeline.py": 5.0,
            "docs/design.md": 5.0,
        }
        file_roles = {
            "libs/retrieval/pipeline.py": "source",
            "docs/design.md": "docs",
        }
        _apply_role_weights(file_scores, file_roles, "fix retrieval bug", "edit")
        assert file_scores["libs/retrieval/pipeline.py"] > file_scores["docs/design.md"]
        assert file_scores["docs/design.md"] == 5.0 * ROLE_WEIGHTS_EDIT["docs"]

    def test_docs_override_when_query_wants_docs(self) -> None:
        file_scores = {
            "libs/retrieval/pipeline.py": 5.0,
            "docs/architecture.md": 5.0,
        }
        file_roles = {
            "libs/retrieval/pipeline.py": "source",
            "docs/architecture.md": "docs",
        }
        _apply_role_weights(file_scores, file_roles, "architecture documentation", "navigate")
        assert file_scores["docs/architecture.md"] == 5.0 * DOCS_OVERRIDE_MULTIPLIER
        assert file_scores["docs/architecture.md"] > file_scores["libs/retrieval/pipeline.py"]

    def test_docs_override_keywords_are_exhaustive(self) -> None:
        expected = {
            "docs",
            "documentation",
            "readme",
            "changelog",
            "architecture",
            "design",
            "spec",
            "adr",
        }
        assert expected == DOCS_OVERRIDE_KEYWORDS

    def test_unknown_role_gets_other_weight(self) -> None:
        file_scores = {"some/weird/file.xyz": 5.0}
        file_roles: dict[str, str] = {}
        _apply_role_weights(file_scores, file_roles, "query", "navigate")
        assert file_scores["some/weird/file.xyz"] == 5.0 * ROLE_WEIGHTS_NAVIGATE["other"]

    def test_test_files_slightly_demoted_in_navigate(self) -> None:
        file_scores = {
            "libs/foo.py": 5.0,
            "tests/test_foo.py": 5.0,
        }
        file_roles = {
            "libs/foo.py": "source",
            "tests/test_foo.py": "test",
        }
        _apply_role_weights(file_scores, file_roles, "how does foo work", "navigate")
        assert file_scores["libs/foo.py"] > file_scores["tests/test_foo.py"]

    def test_config_boosted_by_role_weight(self) -> None:
        file_scores = {
            "libs/foo.py": 5.0,
            "config/settings.yaml": 5.0,
        }
        file_roles = {
            "libs/foo.py": "source",
            "config/settings.yaml": "config",
        }
        _apply_role_weights(file_scores, file_roles, "timeout settings", "navigate")
        assert file_scores["config/settings.yaml"] > file_scores["libs/foo.py"]

    def test_design_in_code_query_still_returns_code(self) -> None:
        file_scores = {
            "libs/retrieval/pipeline.py": 6.0,
            "docs/design.md": 5.0,
        }
        file_roles = {
            "libs/retrieval/pipeline.py": "source",
            "docs/design.md": "docs",
        }
        _apply_role_weights(file_scores, file_roles, "design of the retrieval pipeline", "navigate")
        assert file_scores["libs/retrieval/pipeline.py"] >= file_scores["docs/design.md"]


class TestConfigBoostHeuristic:
    """D2: config file boost on config-ish queries."""

    def test_config_files_injected_on_timeout_query(self) -> None:
        file_scores: dict[str, float] = {
            "libs/auth.py": 3.0,
        }
        file_roles = {
            "libs/auth.py": "source",
            "config/settings.yaml": "config",
        }
        _maybe_boost_config_files("what is the timeout", file_scores, file_roles)
        assert "config/settings.yaml" in file_scores
        assert file_scores["config/settings.yaml"] == CONFIG_BOOST_BASELINE

    def test_config_boost_does_not_override_higher_score(self) -> None:
        file_scores: dict[str, float] = {
            "config/settings.yaml": 2.0,
        }
        file_roles = {
            "config/settings.yaml": "config",
        }
        _maybe_boost_config_files("config timeout", file_scores, file_roles)
        assert file_scores["config/settings.yaml"] == 2.0

    def test_no_boost_on_non_config_query(self) -> None:
        file_scores: dict[str, float] = {}
        file_roles = {
            "config/settings.yaml": "config",
        }
        _maybe_boost_config_files("how does login work", file_scores, file_roles)
        assert "config/settings.yaml" not in file_scores

    def test_case_insensitive_trigger(self) -> None:
        file_scores: dict[str, float] = {}
        file_roles = {"config/settings.yaml": "config"}
        _maybe_boost_config_files("TIMEOUT handling", file_scores, file_roles)
        assert "config/settings.yaml" in file_scores

    def test_only_config_role_files_boosted(self) -> None:
        file_scores: dict[str, float] = {}
        file_roles = {
            "config/settings.yaml": "config",
            "libs/timeout.py": "source",
        }
        _maybe_boost_config_files("timeout", file_scores, file_roles)
        assert "config/settings.yaml" in file_scores
        assert "libs/timeout.py" not in file_scores

    def test_trigger_keywords_completeness(self) -> None:
        expected = {
            "config", "settings", "timeout", "ttl", "schedule",
            "env", "port", "url", "host", "secret", "credential",
            "database", "db", "connection",
        }
        assert CONFIG_TRIGGER_KEYWORDS == expected
