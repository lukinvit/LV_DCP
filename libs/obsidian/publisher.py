"""Obsidian vault publisher — writes markdown pages from indexed project data.

Uses atomic writes (write to .tmp, then rename) to avoid partial pages.
"""

from __future__ import annotations

import time
from pathlib import Path

from libs.obsidian.models import (
    ObsidianFileInfo,
    ObsidianGitInfo,
    ObsidianModuleData,
    ObsidianSymbolInfo,
    SyncReport,
    VaultConfig,
)
from libs.obsidian.templates import (
    render_home_page,
    render_module_page,
    render_recent_changes,
    render_tech_debt,
)
from libs.obsidian.wikilinks import (
    convert_md_links_to_wikilinks,
    make_index_header,
    make_wiki_footer,
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

    def sync_project(  # noqa: PLR0913
        self,
        *,
        project_name: str,
        files: list[ObsidianFileInfo],
        symbols: list[ObsidianSymbolInfo],
        modules: dict[str, ObsidianModuleData],
        hotspots: list[ObsidianGitInfo],
        recent_changes: list[ObsidianGitInfo],
        languages: list[str],
        wiki_dir: Path | None = None,
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
        wiki_dir:
            Optional path to the project's ``.context/wiki/`` directory.
            When provided, the publisher mirrors the LLM-generated wiki
            (``INDEX.md``, ``architecture.md``, ``modules/*.md``) into
            ``<vault>/Projects/<project>/Wiki/`` so the same articles the
            daemon writes locally are visible inside Obsidian. The mirror
            is incremental: stale wiki pages whose source was removed get
            cleaned up so deletions in ``.context/wiki/`` propagate to the
            vault rather than leaking forever (counted in
            ``pages_deleted``).
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

        # Wiki mirror — copy .context/wiki/ articles into <project>/Wiki/.
        # Optional: only runs when caller passes a wiki_dir that exists.
        if wiki_dir is not None and wiki_dir.exists():
            try:
                self._mirror_wiki(
                    wiki_dir,
                    project_dir / "Wiki",
                    report,
                    project_name=project_name,
                )
            except OSError as exc:
                report.errors.append(f"Wiki mirror: {exc}")

        report.duration_seconds = time.monotonic() - t0
        return report

    def _mirror_wiki(
        self,
        src_wiki: Path,
        dst_wiki: Path,
        report: SyncReport,
        *,
        project_name: str,
    ) -> None:
        """Mirror ``.context/wiki/`` into ``<vault>/Projects/<name>/Wiki/``.

        Files written: ``INDEX.md``, ``architecture.md`` (if present),
        and every ``modules/*.md``. Files removed from the source since
        the previous sync get deleted from the destination so vault
        listings don't leak stale articles forever — this is the
        Karpathy LLM-Wiki ``lint`` parity for the vault mirror.

        On the way through, every mirrored file is re-rendered for
        Obsidian: plain markdown links (``[text](modules/foo.md)``) are
        converted to wikilinks (``[[modules/foo|text]]``) so Obsidian's
        graph view and backlink pane light up, and a ``## See also``
        cross-link footer is appended to each article (and a navigation
        header prepended to ``INDEX.md``) so the user can pivot between
        the prose wiki, the project ``Home``, and the auto-generated
        ``Modules/`` tree without leaving the vault. The source under
        ``.context/wiki/`` keeps the portable markdown form — wikilinks
        only ever live in the vault copy.

        Errors on individual files are appended to ``report.errors`` and
        the rest of the mirror continues; a single bad file should not
        wedge the whole sync.
        """
        dst_wiki.mkdir(parents=True, exist_ok=True)
        (dst_wiki / "modules").mkdir(parents=True, exist_ok=True)

        # Track destinations we wrote this pass — anything else under
        # the destination Wiki/ tree is stale and must be removed.
        kept: set[Path] = set()

        # INDEX.md — convert links + prepend the navigation header so
        # the wiki's landing page links out to Home / Modules / Recent
        # Changes inside the same Obsidian project.
        index_src = src_wiki / "INDEX.md"
        if index_src.is_file():
            try:
                dst = dst_wiki / "INDEX.md"
                source = index_src.read_text(encoding="utf-8")
                converted = convert_md_links_to_wikilinks(source)
                header = make_index_header(project_name=project_name)
                self._atomic_write(dst, header + converted)
                kept.add(dst)
                report.pages_written += 1
            except OSError as exc:
                report.errors.append(f"Wiki INDEX.md: {exc}")

        # architecture.md — wikilink-converted, footer appended.
        arch_src = src_wiki / "architecture.md"
        if arch_src.is_file():
            try:
                dst = dst_wiki / "architecture.md"
                source = arch_src.read_text(encoding="utf-8")
                converted = convert_md_links_to_wikilinks(source)
                footer = make_wiki_footer(project_name=project_name, module_short=None)
                self._atomic_write(dst, converted + footer)
                kept.add(dst)
                report.pages_written += 1
            except OSError as exc:
                report.errors.append(f"Wiki architecture.md: {exc}")

        # modules/*.md — wikilink-converted, footer linking back to the
        # auto-generated ``Modules/<short>`` page when the slug starts
        # with a known top-level segment (``apps-cli`` → ``apps``).
        modules_src = src_wiki / "modules"
        if modules_src.is_dir():
            for article in modules_src.glob("*.md"):
                try:
                    dst = dst_wiki / "modules" / article.name
                    source = article.read_text(encoding="utf-8")
                    converted = convert_md_links_to_wikilinks(source)
                    short = _short_module_for(article.stem)
                    footer = make_wiki_footer(project_name=project_name, module_short=short)
                    self._atomic_write(dst, converted + footer)
                    kept.add(dst)
                    report.pages_written += 1
                except OSError as exc:
                    report.errors.append(f"Wiki modules/{article.name}: {exc}")

        # Drift cleanup — remove any *.md under dst_wiki that we did not
        # just write. Keeps the vault as the second copy of the truth in
        # ``.context/wiki/``, not an append-only log.
        for existing in dst_wiki.rglob("*.md"):
            if existing.is_file() and existing not in kept:
                try:
                    existing.unlink()
                    report.pages_deleted += 1
                except OSError as exc:
                    report.errors.append(f"Wiki cleanup {existing.name}: {exc}")


def _short_module_for(article_stem: str) -> str | None:
    """Return the auto-generated ``Modules/<short>.md`` slug for a wiki article.

    The wiki uses ``apps-cli`` / ``libs-wiki`` (first two source path
    segments dash-joined, see :func:`libs.wiki.state.wiki_filename`) but
    the publisher's ``Modules/`` tree slugs at the first segment only
    (``apps`` / ``libs``). This helper picks the first dash-separated
    chunk so the cross-link footer can target a real auto-generated
    page; returns ``None`` for slugs without a dash (e.g. ``README``)
    where there's no useful first-segment fallback to link to.
    """
    if "-" not in article_stem:
        return None
    return article_stem.split("-", 1)[0]
