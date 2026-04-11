"""Package version read from `lv-dcp` (hyphen) metadata, falls back to 'unknown'."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def _load_version() -> str:
    try:
        return version("lv-dcp")
    except PackageNotFoundError:
        return "unknown"


LVDCP_VERSION = _load_version()
