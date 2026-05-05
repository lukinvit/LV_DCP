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


def test_breadcrumb_view_creation() -> None:
    from libs.breadcrumbs.models import BreadcrumbView

    view = BreadcrumbView(
        id=42,
        project_root="/repo/x",
        timestamp=1700000000.0,
        source="pack",  # plain string on read side
        cc_session_id="sess-1",
        os_user="alice",
        cc_account_email="alice@example.com",
        query="how does X work",
        mode="navigate",
        paths_touched=["src/x.py"],
        todo_snapshot=[{"content": "task A", "status": "completed"}],
        turn_summary="last turn was about Y",
    )
    assert view.id == 42
    assert view.source == "pack"
    assert view.paths_touched == ["src/x.py"]


def test_breadcrumb_default_values() -> None:
    bc = Breadcrumb(
        project_root="/repo/x",
        timestamp=1700000000.0,
        source=BreadcrumbSource.PACK,
        os_user="alice",
    )
    assert bc.privacy_mode == "local_only"
    assert bc.cc_session_id is None
    assert bc.cc_account_email is None
    assert bc.query is None
    assert bc.mode is None
    assert bc.paths_touched == []
    assert bc.todo_snapshot is None
    assert bc.turn_summary is None
