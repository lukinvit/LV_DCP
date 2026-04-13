"""Tests for libs/wiki/pack_enrichment.py — keyword matching and enrichment."""

from __future__ import annotations

from pathlib import Path

from libs.wiki.pack_enrichment import enrich_pack_markdown, find_relevant_articles


def _setup_wiki(tmp_path: Path) -> Path:
    """Create a wiki dir with INDEX.md and some articles."""
    wiki_dir = tmp_path / "wiki"
    modules_dir = wiki_dir / "modules"
    modules_dir.mkdir(parents=True)

    # Write articles
    (modules_dir / "auth-service.md").write_text(
        "# auth-service\n\n## Purpose\nHandles authentication and login.\n",
        encoding="utf-8",
    )
    (modules_dir / "voting-service.md").write_text(
        "# voting-service\n\n## Purpose\nManages voting and polls.\n",
        encoding="utf-8",
    )
    (modules_dir / "database-layer.md").write_text(
        "# database-layer\n\n## Purpose\nPostgres connection and ORM models.\n",
        encoding="utf-8",
    )

    # Write INDEX.md
    index_content = """\
# Wiki Index — TestProject

Updated: 2026-04-13 10:00:00
Modules: 3

## Modules
- [auth-service](modules/auth-service.md) — Handles authentication and login.
- [voting-service](modules/voting-service.md) — Manages voting and polls.
- [database-layer](modules/database-layer.md) — Postgres connection and ORM models.
"""
    (wiki_dir / "INDEX.md").write_text(index_content, encoding="utf-8")
    return wiki_dir


class TestFindRelevantArticles:
    def test_finds_matching_article(self, tmp_path: Path) -> None:
        wiki_dir = _setup_wiki(tmp_path)
        results = find_relevant_articles(wiki_dir, "authentication login")
        assert len(results) >= 1
        paths = [r[0] for r in results]
        assert "modules/auth-service.md" in paths

    def test_finds_voting_article(self, tmp_path: Path) -> None:
        wiki_dir = _setup_wiki(tmp_path)
        results = find_relevant_articles(wiki_dir, "voting polls")
        assert len(results) >= 1
        paths = [r[0] for r in results]
        assert "modules/voting-service.md" in paths

    def test_respects_limit(self, tmp_path: Path) -> None:
        wiki_dir = _setup_wiki(tmp_path)
        results = find_relevant_articles(wiki_dir, "service", limit=1)
        assert len(results) == 1

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        wiki_dir = _setup_wiki(tmp_path)
        results = find_relevant_articles(wiki_dir, "xyznonexistent")
        assert results == []

    def test_no_index_returns_empty(self, tmp_path: Path) -> None:
        results = find_relevant_articles(tmp_path / "nonexistent", "anything")
        assert results == []

    def test_returns_content(self, tmp_path: Path) -> None:
        wiki_dir = _setup_wiki(tmp_path)
        results = find_relevant_articles(wiki_dir, "authentication")
        assert len(results) >= 1
        _path, content = results[0]
        assert "auth-service" in content


class TestEnrichPackMarkdown:
    def test_no_articles_returns_original(self) -> None:
        original = "## Top files\n- file1.py"
        result = enrich_pack_markdown(original, [])
        assert result == original

    def test_prepends_wiki_section(self) -> None:
        original = "## Top files\n- file1.py"
        articles = [
            ("modules/auth.md", "# auth\n\nAuth article content."),
        ]
        result = enrich_pack_markdown(original, articles)

        assert result.startswith("## Project knowledge (wiki)")
        assert "Auth article content." in result
        assert "---" in result
        assert result.endswith(original)

    def test_multiple_articles(self) -> None:
        original = "existing"
        articles = [
            ("modules/a.md", "Article A"),
            ("modules/b.md", "Article B"),
        ]
        result = enrich_pack_markdown(original, articles)
        assert "Article A" in result
        assert "Article B" in result
        assert result.endswith("existing")
