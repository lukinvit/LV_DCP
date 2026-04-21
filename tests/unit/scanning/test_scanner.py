from pathlib import Path
from unittest.mock import patch

import pytest
from libs.scanning.scanner import CACHE_REL, ScanResult, scan_project
from libs.storage.sqlite_cache import SqliteCache


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text('"""app package."""\n')
    (tmp_path / "app" / "main.py").write_text("def entry() -> None:\n    return None\n")
    (tmp_path / "README.md").write_text("# demo\n\n## usage\n")
    return tmp_path


def test_scan_project_full_mode_counts_files(sample_project: Path) -> None:
    result = scan_project(sample_project, mode="full")
    assert isinstance(result, ScanResult)
    assert result.files_scanned == 3
    assert result.symbols_extracted >= 2  # entry + usage heading
    assert result.stale_files_removed == 0
    assert result.relations_cached >= result.relations_reparsed


def test_scan_project_returns_elapsed_seconds(sample_project: Path) -> None:
    result = scan_project(sample_project, mode="full")
    assert result.elapsed_seconds >= 0.0


def test_scan_project_incremental_skips_unchanged_files(sample_project: Path) -> None:
    scan_project(sample_project, mode="full")
    result = scan_project(sample_project, mode="incremental")
    # Second incremental run should skip all files (content_hash matches)
    assert result.files_scanned == 3  # still counted, but parsed == 0
    assert result.files_reparsed == 0


def test_scan_project_incremental_reparses_modified(sample_project: Path) -> None:
    scan_project(sample_project, mode="full")
    (sample_project / "app" / "main.py").write_text("def entry() -> int:\n    return 42\n")
    result = scan_project(sample_project, mode="incremental")
    assert result.files_reparsed == 1


def test_scan_incremental_upserts_vectors_for_changed_files(
    sample_project: Path,
) -> None:
    """Daemon-triggered partial scans (mode=incremental, only={...}) must still
    push changed files to Qdrant. Prior regression: the embedding path was
    gated by ``only is None``, so vectors drifted out of sync with the
    SQLite graph whenever the watcher re-indexed a modified file.
    """
    scan_project(sample_project, mode="full")
    (sample_project / "app" / "main.py").write_text(
        "def entry() -> int:\n    return 42\n"
    )

    # Force the qdrant-enabled config branch + observe the embed call.
    class _StubQdrant:
        enabled = True

    class _StubConfig:
        qdrant = _StubQdrant()

    with (
        patch(
            "libs.core.projects_config.load_config",
            return_value=_StubConfig(),
        ),
        patch(
            "libs.embeddings.service.embed_project_files",
            return_value=1,
        ) as mock_embed,
    ):
        scan_project(
            sample_project,
            mode="incremental",
            only={"app/main.py"},
        )

    assert mock_embed.called, (
        "incremental scan with qdrant.enabled should upsert the changed file; "
        "regression: embedding path was previously gated by `only is None`"
    )
    kwargs = mock_embed.call_args.kwargs
    changed = kwargs["changed_files"]
    assert len(changed) == 1
    assert changed[0]["file_path"] == "app/main.py"


def test_scan_marks_file_with_secret_content(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "config.py").write_text(
        "# Accidentally committed:\nAWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
    )
    scan_project(tmp_path, mode="full")
    cache = SqliteCache(tmp_path / CACHE_REL)
    cache.migrate()
    f = cache.get_file("app/config.py")
    assert f is not None
    assert f.has_secrets is True
    cache.close()
