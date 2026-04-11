from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from libs.core import version as version_module
from libs.core.version import LVDCP_VERSION, _load_version


def test_exported_version_is_non_empty_string() -> None:
    assert isinstance(LVDCP_VERSION, str)
    assert len(LVDCP_VERSION) > 0


def test_load_version_returns_installed_version() -> None:
    with patch.object(version_module, "version", return_value="1.2.3"):
        assert _load_version() == "1.2.3"


def test_load_version_falls_back_on_package_not_found() -> None:
    with patch.object(version_module, "version", side_effect=PackageNotFoundError):
        assert _load_version() == "unknown"
