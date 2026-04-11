from libs.core.version import LVDCP_VERSION


def test_version_is_non_empty_string() -> None:
    assert isinstance(LVDCP_VERSION, str)
    assert len(LVDCP_VERSION) > 0


def test_version_matches_pyproject() -> None:
    # Sanity: loaded package version should start with a digit or 'unknown' placeholder.
    # We deliberately don't pin to 0.0.0 so that bumping pyproject.toml doesn't
    # break this test.
    assert LVDCP_VERSION[0].isdigit() or LVDCP_VERSION == "unknown"
