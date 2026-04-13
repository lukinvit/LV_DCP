"""Tests for libs/wiki/index_builder.py — INDEX.md generation."""

from __future__ import annotations

from pathlib import Path

from libs.wiki.index_builder import build_index, write_index


def _create_article(modules_dir: Path, name: str, content: str) -> None:
    modules_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / f"{name}.md").write_text(content, encoding="utf-8")


class TestBuildIndex:
    def test_no_modules_dir(self, tmp_path: Path) -> None:
        result = build_index(tmp_path, "TestProject")
        assert "No modules found" in result

    def test_empty_modules_dir(self, tmp_path: Path) -> None:
        (tmp_path / "modules").mkdir()
        result = build_index(tmp_path, "TestProject")
        assert "No modules found" in result

    def test_single_article(self, tmp_path: Path) -> None:
        _create_article(
            tmp_path / "modules",
            "auth-service",
            "# auth-service\n\n## Purpose\nHandles user authentication and session management.\n\n## Key Components\n- auth.py\n",
        )
        result = build_index(tmp_path, "MyProject")

        assert "# Wiki Index — MyProject" in result
        assert "Modules: 1" in result
        assert "[auth-service](modules/auth-service.md)" in result
        assert "Handles user authentication and session management." in result

    def test_multiple_articles_sorted(self, tmp_path: Path) -> None:
        _create_article(
            tmp_path / "modules",
            "beta-module",
            "# beta\n\n## Purpose\nBeta does beta things.\n",
        )
        _create_article(
            tmp_path / "modules",
            "alpha-module",
            "# alpha\n\n## Purpose\nAlpha does alpha things.\n",
        )
        result = build_index(tmp_path, "SortTest")

        lines = result.splitlines()
        module_lines = [line for line in lines if line.startswith("- [")]
        assert len(module_lines) == 2
        # Sorted alphabetically by filename
        assert "alpha-module" in module_lines[0]
        assert "beta-module" in module_lines[1]

    def test_article_without_purpose(self, tmp_path: Path) -> None:
        _create_article(
            tmp_path / "modules",
            "no-purpose",
            "# no-purpose\n\nSome content without Purpose section.\n",
        )
        result = build_index(tmp_path, "Test")
        assert "[no-purpose](modules/no-purpose.md)" in result
        # Should still appear, just without summary
        assert "—" not in result.split("[no-purpose]")[1].split("\n")[0]


class TestArchitectureSection:
    def test_architecture_included_when_file_exists(self, tmp_path: Path) -> None:
        _create_article(
            tmp_path / "modules",
            "my-module",
            "# my-module\n\n## Purpose\nDoes stuff.\n",
        )
        # Create architecture.md
        (tmp_path / "architecture.md").write_text(
            "# Architecture\n\nOverview of the system.\n", encoding="utf-8"
        )
        result = build_index(tmp_path, "ArchTest")

        assert "## Architecture" in result
        assert "[Architecture Overview](architecture.md)" in result
        assert "## Modules" in result
        assert "[my-module]" in result

    def test_no_architecture_section_when_missing(self, tmp_path: Path) -> None:
        _create_article(
            tmp_path / "modules",
            "my-module",
            "# my-module\n\n## Purpose\nDoes stuff.\n",
        )
        result = build_index(tmp_path, "NoArch")

        assert "## Architecture" not in result
        assert "## Modules" in result

    def test_architecture_only_no_modules(self, tmp_path: Path) -> None:
        (tmp_path / "architecture.md").write_text("# Architecture\n\nOverview.\n", encoding="utf-8")
        result = build_index(tmp_path, "ArchOnly")

        assert "## Architecture" in result
        assert "[Architecture Overview](architecture.md)" in result
        # No modules section when there are no articles
        assert "No modules found" not in result


class TestWriteIndex:
    def test_writes_file(self, tmp_path: Path) -> None:
        _create_article(
            tmp_path / "modules",
            "my-module",
            "# my-module\n\n## Purpose\nDoes stuff.\n",
        )
        write_index(tmp_path, "TestProject")

        index_path = tmp_path / "INDEX.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "# Wiki Index — TestProject" in content
        assert "[my-module]" in content

    def test_creates_wiki_dir(self, tmp_path: Path) -> None:
        wiki_dir = tmp_path / "wiki"
        # No modules dir, but write_index should still create the dir
        write_index(wiki_dir, "Test")
        assert (wiki_dir / "INDEX.md").exists()
