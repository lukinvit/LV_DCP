"""Single source of truth for the LV_DCP package version.

Read via importlib.metadata so it works both in a local editable install
(pyproject.toml version) and in a wheel-installed deployment.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def _load_version() -> str:
    try:
        return version("lv-dcp")
    except PackageNotFoundError:
        return "unknown"


LVDCP_VERSION: str = _load_version()
