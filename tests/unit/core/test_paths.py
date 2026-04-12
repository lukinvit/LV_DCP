from pathlib import Path

import pytest
from libs.core.paths import is_ignored, is_test_path, normalize_path


def test_normalize_path_resolves_relative_to_root(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.py").touch()
    result = normalize_path(tmp_path / "a" / "b" / "c.py", root=tmp_path)
    assert result == "a/b/c.py"


def test_normalize_path_rejects_path_outside_root(tmp_path: Path) -> None:
    # Sibling directory of tmp_path, guaranteed outside on any OS/filesystem.
    outside = tmp_path.parent / "lv_dcp_sibling_fixture" / "elsewhere.py"
    with pytest.raises(ValueError, match="outside root"):
        normalize_path(outside, root=tmp_path)


def test_is_ignored_matches_default_patterns() -> None:
    assert is_ignored("node_modules/foo.js")
    assert is_ignored(".venv/lib/python.py")
    assert is_ignored("__pycache__/x.pyc")
    assert is_ignored(".git/HEAD")


def test_is_ignored_allows_source_files() -> None:
    assert not is_ignored("libs/core/paths.py")
    assert not is_ignored("docs/constitution.md")
    assert not is_ignored("apps/cli/main.py")


def test_is_test_path_true_cases() -> None:
    assert is_test_path("tests/test_foo.py")
    assert is_test_path("app/tests/helper.py")
    assert is_test_path("foo_test.py")
    assert is_test_path("test_bar.py")


def test_is_test_path_false_cases() -> None:
    assert not is_test_path("app/main.py")
    assert not is_test_path("docs/test.md")


def test_env_files_are_ignored_except_example() -> None:
    assert is_ignored(".env")
    assert is_ignored(".env.local")
    assert is_ignored("app/.env.production")
    # .env.example is not in the exact-match list, so it remains indexable
    assert not is_ignored(".env.example")


def test_credentials_json_ignored() -> None:
    assert is_ignored("credentials.json")
    assert is_ignored("app/secrets.json")


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        ".env.staging",
        ".env.development",
        ".env.test",
        ".env.backup",
        ".env.prod",
        ".env.custom.override",
        "sub/dir/.env.dev",
    ],
)
def test_env_variants_are_ignored(path: str) -> None:
    assert is_ignored(path) is True


def test_env_example_is_not_ignored() -> None:
    assert is_ignored(".env.example") is False
    assert is_ignored("sub/.env.example") is False


class TestPhase4IgnorePatterns:
    def test_playwright_mcp_ignored(self) -> None:
        assert is_ignored(".playwright-mcp/page-2026.yml")

    def test_superpowers_ignored(self) -> None:
        assert is_ignored(".superpowers/brainstorm/content/foo.html")

    def test_minified_js_ignored(self) -> None:
        assert is_ignored("static/bundle.min.js")

    def test_minified_css_ignored(self) -> None:
        assert is_ignored("static/style.min.css")

    def test_regular_js_not_ignored(self) -> None:
        assert not is_ignored("apps/ui/static/js/dashboard.js")

    def test_regular_css_not_ignored(self) -> None:
        assert not is_ignored("apps/ui/static/css/style.css")
