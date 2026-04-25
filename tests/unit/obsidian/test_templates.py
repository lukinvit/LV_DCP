"""Tests for libs.obsidian.templates."""

from __future__ import annotations

from libs.obsidian.templates import render_home_page, render_module_page


class TestRenderHomePage:
    def test_has_frontmatter(self) -> None:
        result = render_home_page(
            project_name="MyProject",
            languages=["python", "yaml"],
            file_count=42,
            symbol_count=100,
            scan_date="2026-04-13",
        )
        assert result.startswith("---\n")
        assert "project: MyProject" in result
        assert "scan_date: 2026-04-13" in result

    def test_has_project_data(self) -> None:
        result = render_home_page(
            project_name="MyProject",
            languages=["python"],
            file_count=42,
            symbol_count=100,
            scan_date="2026-04-13",
        )
        assert "# MyProject" in result
        assert "| Files | 42 |" in result
        assert "| Symbols | 100 |" in result
        assert "python" in result

    def test_empty_languages(self) -> None:
        result = render_home_page(
            project_name="Empty",
            languages=[],
            file_count=0,
            symbol_count=0,
            scan_date="2026-04-13",
        )
        assert "none" in result


class TestRenderModulePage:
    def test_has_wikilinks_for_dependencies(self) -> None:
        result = render_module_page(
            module_name="core",
            project_name="MyProject",
            file_count=10,
            symbol_count=30,
            top_symbols=["Foo", "bar"],
            dependencies=["utils", "config"],
            dependents=["api"],
            scan_date="2026-04-13",
        )
        assert "[[utils]]" in result
        assert "[[config]]" in result
        assert "[[api]]" in result

    def test_has_frontmatter_and_stats(self) -> None:
        result = render_module_page(
            module_name="core",
            project_name="MyProject",
            file_count=10,
            symbol_count=30,
            top_symbols=[],
            dependencies=[],
            dependents=[],
            scan_date="2026-04-13",
        )
        assert result.startswith("---\n")
        assert "module: core" in result
        assert "| Files | 10 |" in result
        assert "[[MyProject]]" in result

    def test_top_symbols_listed(self) -> None:
        result = render_module_page(
            module_name="core",
            project_name="P",
            file_count=1,
            symbol_count=2,
            top_symbols=["ClassA", "func_b"],
            dependencies=[],
            dependents=[],
            scan_date="2026-04-13",
        )
        assert "`ClassA`" in result
        assert "`func_b`" in result

    def test_links_to_wiki_index(self) -> None:
        """v0.8.67 — every Modules/<name>.md must point at the wiki INDEX
        so the user can pivot from structural stats to the LLM-generated
        prose articles for that module."""
        result = render_module_page(
            module_name="apps",
            project_name="LV_DCP",
            file_count=1,
            symbol_count=1,
            top_symbols=[],
            dependencies=[],
            dependents=[],
            scan_date="2026-04-13",
        )
        assert "## Wiki articles" in result
        assert "[[Projects/LV_DCP/Wiki/INDEX|wiki index]]" in result
        # The hint mentions the slug prefix so the user knows what to
        # search for in the index.
        assert "`apps-*`" in result


class TestRenderHomePageWikiLink:
    def test_home_links_to_wiki_index(self) -> None:
        """v0.8.67 — the project Home must surface the wiki entry point
        in its navigation block, alongside Recent Changes / Tech Debt."""
        result = render_home_page(
            project_name="LV_DCP",
            languages=["python"],
            file_count=10,
            symbol_count=20,
            scan_date="2026-04-13",
        )
        assert "[[Wiki/INDEX|Wiki index]]" in result
