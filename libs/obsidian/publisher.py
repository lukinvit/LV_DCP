"""Obsidian vault publisher — writes markdown pages from indexed project data.

Uses atomic writes (write to .tmp, then rename) to avoid partial pages.
"""

from __future__ import annotations

import time
from pathlib import Path

from libs.obsidian.models import SyncReport, VaultConfig
from libs.obsidian.templates import (
    render_home_page,
    render_module_page,
    render_recent_changes,
    render_tech_debt,
)


class ObsidianPublisher:
    """Publishes LV_DCP project data as Obsidian vault pages."""

    def __init__(self, config: VaultConfig) -> None:
        self.config = config

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content to a temp file, then atomically rename."""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

    def sync_project(
        self,
        *,
        project_name: str,
        files: list[dict],
        symbols: list[dict],
        modules: dict[str, dict],
        hotspots: list[dict],
        recent_changes: list[dict],
        languages: list[str],
    ) -> SyncReport:
        """Sync project data to Obsidian vault.

        Parameters
        ----------
        project_name:
            Human-readable project name.
        files:
            List of file dicts (at minimum: path, language).
        symbols:
            List of symbol dicts (at minimum: name, file_path, symbol_type).
        modules:
            Mapping of module_name -> dict with keys: file_count, symbol_count,
            top_symbols, dependencies, dependents.
        hotspots:
            List of hotspot dicts for tech debt page.
        recent_changes:
            List of change dicts for recent changes page.
        languages:
            List of detected languages.
        """
        t0 = time.monotonic()
        report = SyncReport(project_name=project_name)
        scan_date = time.strftime("%Y-%m-%d")

        # Create directory structure
        project_dir = self.config.vault_path / "Projects" / project_name
        modules_dir = project_dir / "Modules"
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            modules_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            report.errors.append(f"Failed to create directories: {exc}")
            report.duration_seconds = time.monotonic() - t0
            return report

        # Home page
        try:
            home_md = render_home_page(
                project_name=project_name,
                languages=languages,
                file_count=len(files),
                symbol_count=len(symbols),
                scan_date=scan_date,
            )
            self._atomic_write(project_dir / "Home.md", home_md)
            report.pages_written += 1
        except Exception as exc:
            report.errors.append(f"Home.md: {exc}")

        # Module pages
        for mod_name, mod_data in modules.items():
            try:
                mod_md = render_module_page(
                    module_name=mod_name,
                    project_name=project_name,
                    file_count=mod_data.get("file_count", 0),
                    symbol_count=mod_data.get("symbol_count", 0),
                    top_symbols=mod_data.get("top_symbols", []),
                    dependencies=mod_data.get("dependencies", []),
                    dependents=mod_data.get("dependents", []),
                    scan_date=scan_date,
                )
                self._atomic_write(modules_dir / f"{mod_name}.md", mod_md)
                report.pages_written += 1
            except Exception as exc:
                report.errors.append(f"Module {mod_name}: {exc}")

        # Recent Changes page
        try:
            changes_md = render_recent_changes(
                project_name=project_name,
                changes=recent_changes,
                scan_date=scan_date,
            )
            self._atomic_write(project_dir / "Recent Changes.md", changes_md)
            report.pages_written += 1
        except Exception as exc:
            report.errors.append(f"Recent Changes.md: {exc}")

        # Tech Debt page
        try:
            debt_md = render_tech_debt(
                project_name=project_name,
                hotspots=hotspots,
                scan_date=scan_date,
            )
            self._atomic_write(project_dir / "Tech Debt.md", debt_md)
            report.pages_written += 1
        except Exception as exc:
            report.errors.append(f"Tech Debt.md: {exc}")

        report.duration_seconds = time.monotonic() - t0
        return report
