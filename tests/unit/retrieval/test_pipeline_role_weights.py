"""Tests for role-weighted score fusion (D1), config boost (D2), graph depth (D3)."""

from __future__ import annotations

from libs.retrieval.pipeline import (
    CONFIG_BOOST_FRACTION,
    CONFIG_TRIGGER_KEYWORDS,
    DOCS_OVERRIDE_KEYWORDS,
    DOCS_OVERRIDE_MULTIPLIER,
    GRAPH_EXPANSION_DEPTH,
    GRAPH_EXPANSION_DEPTH_EDIT,
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

    def test_config_files_boosted_when_already_scored(self) -> None:
        """Config files already in the candidate pool are boosted to baseline."""
        file_scores: dict[str, float] = {
            "libs/auth.py": 3.0,
            "config/settings.yaml": 0.3,  # already found by FTS/symbol
        }
        file_roles = {
            "libs/auth.py": "source",
            "config/settings.yaml": "config",
        }
        _maybe_boost_config_files("what is the timeout", file_scores, file_roles)
        assert file_scores["config/settings.yaml"] == 3.0 * CONFIG_BOOST_FRACTION

    def test_zero_score_config_files_not_injected(self) -> None:
        """Config files absent from candidate pool are not injected.

        Prevents unrelated config files (e.g. logging.json) appearing for
        database or timeout queries where they have no FTS signal.
        """
        file_scores: dict[str, float] = {"libs/auth.py": 3.0}
        file_roles = {
            "libs/auth.py": "source",
            "config/logging.json": "config",  # not in candidate pool
        }
        _maybe_boost_config_files("timeout database", file_scores, file_roles)
        assert "config/logging.json" not in file_scores

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
        """Config boost still fires for uppercase query words."""
        file_scores: dict[str, float] = {"libs/auth.py": 2.0, "config/settings.yaml": 0.1}
        file_roles = {"config/settings.yaml": "config", "libs/auth.py": "source"}
        _maybe_boost_config_files("TIMEOUT handling", file_scores, file_roles)
        assert file_scores["config/settings.yaml"] == 2.0 * CONFIG_BOOST_FRACTION

    def test_only_config_role_files_boosted(self) -> None:
        """Only files with role='config' are boosted; source files are untouched."""
        file_scores: dict[str, float] = {
            "config/settings.yaml": 0.5,
            "libs/timeout.py": 1.0,
        }
        file_roles = {
            "config/settings.yaml": "config",
            "libs/timeout.py": "source",
        }
        before_source = file_scores["libs/timeout.py"]
        _maybe_boost_config_files("timeout", file_scores, file_roles)
        assert file_scores["config/settings.yaml"] >= 0.5
        assert file_scores["libs/timeout.py"] == before_source

    def test_trigger_keywords_completeness(self) -> None:
        expected = {
            "config",
            "settings",
            "timeout",
            "ttl",
            "schedule",
            "lifetime",
            "env",
            "port",
            "url",
            "host",
            "secret",
            "credential",
            "database",
            "db",
            "connection",
        }
        assert expected == CONFIG_TRIGGER_KEYWORDS

    def test_no_substring_match_on_credentials(self) -> None:
        """Word 'credentials' must NOT match keyword 'credential'."""
        file_scores: dict[str, float] = {"libs/auth.py": 5.0}
        file_roles = {"libs/auth.py": "source", "config/settings.yaml": "config"}
        _maybe_boost_config_files("validates credentials", file_scores, file_roles)
        assert "config/settings.yaml" not in file_scores

    def test_no_substring_match_on_import(self) -> None:
        """Word 'import' must NOT match keyword 'port'."""
        file_scores: dict[str, float] = {"libs/main.py": 5.0}
        file_roles = {"libs/main.py": "source", "config/settings.yaml": "config"}
        _maybe_boost_config_files("import models", file_scores, file_roles)
        assert "config/settings.yaml" not in file_scores


class TestGraphDepthTuning:
    """D3: graph expansion depth=3 for edit mode."""

    def test_navigate_depth_unchanged(self) -> None:
        assert GRAPH_EXPANSION_DEPTH == 2

    def test_edit_depth_is_three(self) -> None:
        assert GRAPH_EXPANSION_DEPTH_EDIT == 3

    def test_stage_graph_uses_edit_depth(self) -> None:
        """Verify _stage_graph passes the correct depth based on mode."""
        from unittest.mock import MagicMock, patch

        from libs.retrieval.pipeline import RetrievalPipeline

        mock_cache = MagicMock()
        mock_cache.iter_files.return_value = []
        mock_fts = MagicMock()
        mock_fts.search.return_value = [("libs/foo.py", 1.0)]
        mock_symbols = MagicMock()
        mock_symbols.lookup.return_value = []
        mock_symbols._symbols = []

        mock_graph = MagicMock()

        captured_depths: list[int] = []

        def fake_expand(seeds: object, graph: object, *, depth: int, decay: float) -> list[object]:
            captured_depths.append(depth)
            return []

        with patch("libs.retrieval.pipeline.expand_via_graph", side_effect=fake_expand):
            pipeline = RetrievalPipeline(
                cache=mock_cache, fts=mock_fts, symbols=mock_symbols, graph=mock_graph
            )
            pipeline.retrieve("edit something", mode="edit")
            pipeline.retrieve("find something", mode="navigate")

        assert captured_depths == [3, 2]
