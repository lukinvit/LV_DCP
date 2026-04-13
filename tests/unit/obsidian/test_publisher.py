"""Tests for libs.obsidian.publisher."""

from __future__ import annotations

from pathlib import Path

from libs.obsidian.models import VaultConfig
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
