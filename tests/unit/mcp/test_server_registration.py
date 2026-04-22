import asyncio


def test_server_exposes_all_registered_tools() -> None:
    from apps.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    assert tool_names == {
        "lvdcp_scan",
        "lvdcp_pack",
        "lvdcp_inspect",
        "lvdcp_explain",
        "lvdcp_status",
        "lvdcp_neighbors",
        "lvdcp_cross_project_patterns",
        "lvdcp_history",
        "lvdcp_removed_since",
        "lvdcp_when",
        "lvdcp_memory_propose",
        "lvdcp_memory_list",
    }


def test_server_tool_descriptions_contain_call_triggers() -> None:
    from apps.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}

    # lvdcp_pack description must tell Claude when to call
    pack_desc = by_name["lvdcp_pack"].description or ""
    assert "CALL THIS BEFORE" in pack_desc
    assert "edit task" in pack_desc.lower()

    # lvdcp_scan description must tell Claude when NOT to call it frequently
    scan_desc = by_name["lvdcp_scan"].description or ""
    assert "DO NOT CALL" in scan_desc

    # lvdcp_removed_since must tell Claude when to call it (US1)
    rs_desc = by_name["lvdcp_removed_since"].description or ""
    assert "CALL THIS WHEN" in rs_desc
    assert "DO NOT CALL" in rs_desc

    # lvdcp_when must tell Claude when to call it (US2)
    when_desc = by_name["lvdcp_when"].description or ""
    assert "CALL THIS WHEN" in when_desc
    assert "DO NOT CALL" in when_desc
