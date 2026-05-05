import dataclasses

from libs.breadcrumbs.models import Breadcrumb, BreadcrumbSource


def test_breadcrumb_is_frozen() -> None:
    bc = Breadcrumb(
        project_root="/repo/x",
        timestamp=1700000000.0,
        source=BreadcrumbSource.PACK,
        os_user="alice",
        privacy_mode="local_only",
    )
    assert dataclasses.is_dataclass(bc)
    try:
        bc.os_user = "bob"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError")


def test_breadcrumb_source_values() -> None:
    expected = {"pack", "status", "hook_stop", "hook_pre_compact", "hook_subagent_stop", "manual"}
    assert {s.value for s in BreadcrumbSource} == expected
