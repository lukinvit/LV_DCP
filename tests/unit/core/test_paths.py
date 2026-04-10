from pathlib import Path

from libs.core.paths import is_ignored, normalize_path


def test_normalize_path_resolves_relative_to_root(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.py").touch()
    result = normalize_path(tmp_path / "a" / "b" / "c.py", root=tmp_path)
    assert result == "a/b/c.py"


def test_normalize_path_rejects_path_outside_root(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError, match="outside root"):
        normalize_path(Path("/tmp/elsewhere.py"), root=tmp_path)


def test_is_ignored_matches_default_patterns() -> None:
    assert is_ignored("node_modules/foo.js")
    assert is_ignored(".venv/lib/python.py")
    assert is_ignored("__pycache__/x.pyc")
    assert is_ignored(".git/HEAD")


def test_is_ignored_allows_source_files() -> None:
    assert not is_ignored("libs/core/paths.py")
    assert not is_ignored("docs/constitution.md")
    assert not is_ignored("apps/cli/main.py")
