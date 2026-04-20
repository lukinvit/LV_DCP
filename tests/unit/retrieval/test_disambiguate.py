"""Tests for the coverage disambiguation hint generator."""

from __future__ import annotations

from libs.retrieval.disambiguate import format_suggestion_hint, suggest_disambiguators


class TestSuggestDisambiguators:
    def test_empty_files_returns_empty(self) -> None:
        assert suggest_disambiguators("anything", []) == []

    def test_returns_discriminative_token_from_parent_dir(self) -> None:
        files = [
            "apps/agent/daemon.py",
            "apps/backend/main.py",
            "apps/worker/queue.py",
        ]
        suggestions = suggest_disambiguators("find main logic", files, limit=3)
        # At least one of agent/backend/worker should appear — they split the set.
        assert any(t in {"agent", "backend", "worker"} for t in suggestions)

    def test_omits_tokens_already_in_query(self) -> None:
        files = ["apps/agent/run.py", "apps/backend/run.py"]
        suggestions = suggest_disambiguators("agent", files, limit=3)
        assert "agent" not in suggestions

    def test_omits_generic_stopwords(self) -> None:
        files = [
            "src/app/foo.py",
            "src/lib/bar.py",
            "tests/unit/baz.py",
        ]
        suggestions = suggest_disambiguators("anything", files)
        for stop in ("src", "app", "lib", "tests"):
            assert stop not in suggestions

    def test_token_present_in_all_candidates_is_useless(self) -> None:
        files = [
            "apps/agent/daemon.py",
            "apps/agent/queue.py",
            "apps/agent/worker.py",
        ]
        # 'agent' is in every path → not helpful as a disambiguator.
        suggestions = suggest_disambiguators("find something", files)
        assert "agent" not in suggestions

    def test_respects_limit(self) -> None:
        files = [
            "pkg/alpha/mod.py",
            "pkg/beta/mod.py",
            "pkg/gamma/mod.py",
            "pkg/delta/mod.py",
            "pkg/epsilon/mod.py",
        ]
        suggestions = suggest_disambiguators("mod", files, limit=2)
        assert len(suggestions) <= 2

    def test_returns_alphabetically_stable_on_ties(self) -> None:
        # Build a case where two tokens have equal distinctiveness.
        files = [
            "apps/alpha/x.py",
            "apps/beta/x.py",
        ]
        a = suggest_disambiguators("x", files, limit=2)
        b = suggest_disambiguators("x", files, limit=2)
        assert a == b


class TestFormatSuggestionHint:
    def test_empty_returns_empty_string(self) -> None:
        assert format_suggestion_hint([]) == ""

    def test_single_suggestion(self) -> None:
        hint = format_suggestion_hint(["agent"])
        assert "`agent`" in hint
        assert "Try adding" in hint

    def test_multiple_suggestions(self) -> None:
        hint = format_suggestion_hint(["agent", "worker"])
        assert "`agent`" in hint
        assert "`worker`" in hint
