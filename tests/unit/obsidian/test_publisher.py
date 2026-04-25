"""Tests for libs.obsidian.publisher."""

from __future__ import annotations

from pathlib import Path

from libs.obsidian.models import SyncReport, VaultConfig
from libs.obsidian.publisher import ObsidianPublisher


class TestObsidianPublisher:
    def test_creates_project_directory(self, tmp_path: Path) -> None:
        config = VaultConfig(vault_path=tmp_path)
        publisher = ObsidianPublisher(config)
        publisher.sync_project(
            project_name="TestProj",
            files=[],
            symbols=[],
            modules={},
            hotspots=[],
            recent_changes=[],
            languages=[],
        )
        assert (tmp_path / "Projects" / "TestProj").is_dir()
        assert (tmp_path / "Projects" / "TestProj" / "Modules").is_dir()

    def test_writes_module_pages(self, tmp_path: Path) -> None:
        config = VaultConfig(vault_path=tmp_path)
        publisher = ObsidianPublisher(config)
        publisher.sync_project(
            project_name="TestProj",
            files=[{"path": "core/main.py", "language": "python"}],
            symbols=[{"name": "foo", "file_path": "core/main.py", "symbol_type": "function"}],
            modules={
                "core": {
                    "file_count": 1,
                    "symbol_count": 1,
                    "top_symbols": ["foo"],
                    "dependencies": [],
                    "dependents": [],
                },
            },
            hotspots=[],
            recent_changes=[],
            languages=["python"],
        )
        module_page = tmp_path / "Projects" / "TestProj" / "Modules" / "core.md"
        assert module_page.exists()
        content = module_page.read_text(encoding="utf-8")
        assert "core" in content
        assert "`foo`" in content

    def test_returns_report_with_counts(self, tmp_path: Path) -> None:
        config = VaultConfig(vault_path=tmp_path)
        publisher = ObsidianPublisher(config)
        report = publisher.sync_project(
            project_name="TestProj",
            files=[],
            symbols=[],
            modules={
                "alpha": {
                    "file_count": 0,
                    "symbol_count": 0,
                    "top_symbols": [],
                    "dependencies": [],
                    "dependents": [],
                },
                "beta": {
                    "file_count": 0,
                    "symbol_count": 0,
                    "top_symbols": [],
                    "dependencies": [],
                    "dependents": [],
                },
            },
            hotspots=[],
            recent_changes=[],
            languages=[],
        )
        # Home + 2 modules + Recent Changes + Tech Debt = 5
        assert report.pages_written == 5
        assert report.project_name == "TestProj"
        assert report.errors == []
        assert report.duration_seconds >= 0.0

    def test_home_page_written(self, tmp_path: Path) -> None:
        config = VaultConfig(vault_path=tmp_path)
        publisher = ObsidianPublisher(config)
        publisher.sync_project(
            project_name="Proj",
            files=[{"path": "a.py", "language": "python"}],
            symbols=[],
            modules={},
            hotspots=[],
            recent_changes=[],
            languages=["python"],
        )
        home = tmp_path / "Projects" / "Proj" / "Home.md"
        assert home.exists()
        content = home.read_text(encoding="utf-8")
        assert "# Proj" in content
        assert "| Files | 1 |" in content


def _empty_sync(
    publisher: ObsidianPublisher,
    *,
    project_name: str,
    wiki_dir: Path | None = None,
) -> SyncReport:
    """Invoke ``sync_project`` with empty inputs, optionally a wiki dir.

    Wraps the call so each test stays a one-liner without re-typing the
    six empty-list arguments and without tripping mypy on a ``**dict``
    splat into a heterogeneously-typed signature.
    """
    return publisher.sync_project(
        project_name=project_name,
        files=[],
        symbols=[],
        modules={},
        hotspots=[],
        recent_changes=[],
        languages=[],
        wiki_dir=wiki_dir,
    )


class TestWikiMirror:
    """v0.8.66 — ObsidianPublisher mirrors .context/wiki/ into <project>/Wiki/."""

    def test_no_wiki_dir_no_wiki_pages(self, tmp_path: Path) -> None:
        """Publisher must not create Wiki/ when wiki_dir is None — backward
        compat for existing callers that don't pass it."""
        config = VaultConfig(vault_path=tmp_path)
        publisher = ObsidianPublisher(config)
        report = _empty_sync(publisher, project_name="Proj")
        assert not (tmp_path / "Projects" / "Proj" / "Wiki").exists()
        # Same page count as before v0.8.66: Home + Recent Changes + Tech Debt = 3.
        assert report.pages_written == 3

    def test_missing_wiki_dir_is_silent(self, tmp_path: Path) -> None:
        """Publisher must not error when wiki_dir points to a missing path."""
        config = VaultConfig(vault_path=tmp_path)
        publisher = ObsidianPublisher(config)
        report = _empty_sync(publisher, project_name="Proj", wiki_dir=tmp_path / "does-not-exist")
        assert not (tmp_path / "Projects" / "Proj" / "Wiki").exists()
        assert report.errors == []

    def test_mirrors_index_architecture_and_modules(self, tmp_path: Path) -> None:
        """Wiki/ inside the vault must contain the full INDEX, architecture,
        and per-module articles — the same artifacts the daemon writes
        locally to .context/wiki/.

        Since v0.8.67 the body is wrapped with a navigation header
        (INDEX.md) or a ``## See also`` footer (everything else), so we
        check for substring presence of the original body rather than
        byte-for-byte equality.
        """
        wiki_src = tmp_path / "wiki-src"
        (wiki_src / "modules").mkdir(parents=True)
        (wiki_src / "INDEX.md").write_text("# Wiki Index\n", encoding="utf-8")
        (wiki_src / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
        (wiki_src / "modules" / "core.md").write_text("# core\nbody\n", encoding="utf-8")
        (wiki_src / "modules" / "api.md").write_text("# api\nbody\n", encoding="utf-8")

        config = VaultConfig(vault_path=tmp_path / "vault")
        publisher = ObsidianPublisher(config)
        report = _empty_sync(publisher, project_name="Proj", wiki_dir=wiki_src)

        wiki_dst = tmp_path / "vault" / "Projects" / "Proj" / "Wiki"
        index_body = (wiki_dst / "INDEX.md").read_text(encoding="utf-8")
        assert "# Wiki Index" in index_body
        arch_body = (wiki_dst / "architecture.md").read_text(encoding="utf-8")
        assert "# Architecture" in arch_body
        assert (wiki_dst / "modules" / "core.md").exists()
        assert (wiki_dst / "modules" / "api.md").exists()
        # 3 baseline (Home + Recent Changes + Tech Debt) + 4 wiki = 7 written.
        assert report.pages_written == 7
        assert report.errors == []

    def test_index_links_converted_to_wikilinks(self, tmp_path: Path) -> None:
        """v0.8.67 — INDEX.md mirrored into vault has its markdown links
        rewritten to Obsidian ``[[wikilinks]]`` so the graph view lights up."""
        wiki_src = tmp_path / "wiki-src"
        (wiki_src / "modules").mkdir(parents=True)
        (wiki_src / "INDEX.md").write_text(
            "# Wiki Index\n\n- [apps-cli](modules/apps-cli.md)\n",
            encoding="utf-8",
        )
        (wiki_src / "modules" / "apps-cli.md").write_text("# apps-cli\n", encoding="utf-8")

        config = VaultConfig(vault_path=tmp_path / "vault")
        publisher = ObsidianPublisher(config)
        _empty_sync(publisher, project_name="LV_DCP", wiki_dir=wiki_src)

        index_body = (tmp_path / "vault" / "Projects" / "LV_DCP" / "Wiki" / "INDEX.md").read_text(
            encoding="utf-8"
        )
        assert "[[modules/apps-cli|apps-cli]]" in index_body
        # Original markdown form must be gone — proves the rewrite ran.
        assert "[apps-cli](modules/apps-cli.md)" not in index_body

    def test_index_gets_navigation_header(self, tmp_path: Path) -> None:
        """v0.8.67 — the mirrored INDEX.md is prepended with a nav blockquote
        linking to Home / Modules / Recent Changes inside the same project."""
        wiki_src = tmp_path / "wiki-src"
        (wiki_src / "modules").mkdir(parents=True)
        (wiki_src / "INDEX.md").write_text("# Wiki Index\n", encoding="utf-8")

        config = VaultConfig(vault_path=tmp_path / "vault")
        publisher = ObsidianPublisher(config)
        _empty_sync(publisher, project_name="LV_DCP", wiki_dir=wiki_src)

        index_body = (tmp_path / "vault" / "Projects" / "LV_DCP" / "Wiki" / "INDEX.md").read_text(
            encoding="utf-8"
        )
        assert "[[Projects/LV_DCP/Home|Project home]]" in index_body
        assert "[[Projects/LV_DCP/Modules|Modules]]" in index_body

    def test_module_article_gets_see_also_footer(self, tmp_path: Path) -> None:
        """v0.8.67 — every modules/<slug>.md mirrored into the vault must
        end with a ``## See also`` block linking back to Home, the wiki
        index, and (when the slug has a dash) the auto-generated
        ``Modules/<short>`` stats page."""
        wiki_src = tmp_path / "wiki-src"
        (wiki_src / "modules").mkdir(parents=True)
        (wiki_src / "modules" / "apps-cli.md").write_text("# apps-cli\nbody\n", encoding="utf-8")

        config = VaultConfig(vault_path=tmp_path / "vault")
        publisher = ObsidianPublisher(config)
        _empty_sync(publisher, project_name="LV_DCP", wiki_dir=wiki_src)

        body = (
            tmp_path / "vault" / "Projects" / "LV_DCP" / "Wiki" / "modules" / "apps-cli.md"
        ).read_text(encoding="utf-8")
        assert "## See also" in body
        assert "[[Projects/LV_DCP/Home|Project home]]" in body
        assert "[[Projects/LV_DCP/Wiki/INDEX|Wiki index]]" in body
        assert "[[Projects/LV_DCP/Modules/apps|Module stats: apps]]" in body

    def test_module_article_without_dash_omits_modules_link(self, tmp_path: Path) -> None:
        """A slug without a dash (e.g. ``README``) has no first-segment
        fallback, so the Modules stats link must be omitted from the
        footer rather than pointing at a nonsense target."""
        wiki_src = tmp_path / "wiki-src"
        (wiki_src / "modules").mkdir(parents=True)
        (wiki_src / "modules" / "README.md").write_text("# readme\n", encoding="utf-8")

        config = VaultConfig(vault_path=tmp_path / "vault")
        publisher = ObsidianPublisher(config)
        _empty_sync(publisher, project_name="LV_DCP", wiki_dir=wiki_src)

        body = (
            tmp_path / "vault" / "Projects" / "LV_DCP" / "Wiki" / "modules" / "README.md"
        ).read_text(encoding="utf-8")
        assert "Module stats:" not in body
        assert "[[Projects/LV_DCP/Wiki/INDEX|Wiki index]]" in body

    def test_drift_cleanup_removes_stale_articles(self, tmp_path: Path) -> None:
        """A module that disappears from .context/wiki/ must also disappear
        from the vault on the next sync — the vault must not become an
        append-only log of every article that ever existed."""
        wiki_src = tmp_path / "wiki-src"
        (wiki_src / "modules").mkdir(parents=True)
        (wiki_src / "INDEX.md").write_text("# Wiki Index\n", encoding="utf-8")
        (wiki_src / "modules" / "alpha.md").write_text("alpha\n", encoding="utf-8")
        (wiki_src / "modules" / "beta.md").write_text("beta\n", encoding="utf-8")

        config = VaultConfig(vault_path=tmp_path / "vault")
        publisher = ObsidianPublisher(config)
        _empty_sync(publisher, project_name="Proj", wiki_dir=wiki_src)

        # Drop one module and re-sync.
        (wiki_src / "modules" / "beta.md").unlink()
        report2 = _empty_sync(publisher, project_name="Proj", wiki_dir=wiki_src)

        wiki_dst = tmp_path / "vault" / "Projects" / "Proj" / "Wiki"
        assert (wiki_dst / "modules" / "alpha.md").exists()
        assert not (wiki_dst / "modules" / "beta.md").exists()
        assert report2.pages_deleted == 1
