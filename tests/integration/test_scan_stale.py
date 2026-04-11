"""Test that ctx scan removes cache entries for files deleted from disk."""

from pathlib import Path

from apps.cli.commands.scan import CACHE_REL
from apps.cli.main import app
from libs.storage.sqlite_cache import SqliteCache
from typer.testing import CliRunner

runner = CliRunner()


def test_scan_removes_deleted_files(tmp_path: Path) -> None:
    # Arrange: tiny two-file project
    (tmp_path / "a.py").write_text("def alpha() -> None:\n    pass\n")
    (tmp_path / "b.py").write_text("def beta() -> None:\n    pass\n")

    # First scan — both files indexed
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0, result.output

    cache = SqliteCache(tmp_path / CACHE_REL)
    cache.migrate()
    paths_after_first = {f.path for f in cache.iter_files()}
    assert paths_after_first == {"a.py", "b.py"}
    symbols_before = {s.name for s in cache.iter_symbols()}
    assert "alpha" in symbols_before
    assert "beta" in symbols_before
    cache.close()

    # Act: delete b.py and re-scan
    (tmp_path / "b.py").unlink()
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0, result.output

    # Assert: cache no longer contains b.py or its symbols/relations
    cache = SqliteCache(tmp_path / CACHE_REL)
    cache.migrate()
    paths_after_second = {f.path for f in cache.iter_files()}
    assert paths_after_second == {"a.py"}
    symbols_after = {s.name for s in cache.iter_symbols()}
    assert "alpha" in symbols_after
    assert "beta" not in symbols_after
    relations_after = [r for r in cache.iter_relations()]
    assert all(r.src_ref != "b.py" for r in relations_after)
    cache.close()
