"""Verify the lvdcp_status tool is registered and callable via MCP stdio."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from libs.scanning.scanner import scan_project
from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


async def test_mcp_stdio_handshake_lists_status(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text("def hi() -> None:\n    return None\n")
    scan_project(tmp_path, mode="full")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "apps.mcp.server"],
        env={**os.environ, "PYTHONPATH": _PROJECT_ROOT},
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert "lvdcp_status" in names

        result = await session.call_tool("lvdcp_status", arguments={})
        assert result.content, "lvdcp_status returned no content"
