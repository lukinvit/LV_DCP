"""End-to-end MCP handshake test.

Spawns the MCP server as a real subprocess via stdio transport,
completes the initialize handshake, lists tools, and calls lvdcp_inspect.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from libs.scanning.scanner import scan_project
from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters

# Compute the project root at module load time (sync context — no ASYNC240)
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


async def test_mcp_stdio_handshake_lists_tools(tmp_path: Path) -> None:
    # Arrange: a minimal scanned project so lvdcp_inspect has something to return
    (tmp_path / "hello.py").write_text("def hi() -> None:\n    return None\n")
    scan_project(tmp_path, mode="full")

    # Make sure the subprocess can find the project root on PYTHONPATH
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "apps.mcp.server"],
        env={**os.environ, "PYTHONPATH": _PROJECT_ROOT},
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools_result = await session.list_tools()
        tool_names = {t.name for t in tools_result.tools}
        assert tool_names == {
            "lvdcp_scan",
            "lvdcp_pack",
            "lvdcp_inspect",
            "lvdcp_explain",
            "lvdcp_status",
            "lvdcp_neighbors",
            "lvdcp_cross_project_patterns",
            "lvdcp_history",
            "lvdcp_memory_propose",
            "lvdcp_memory_list",
        }, f"unexpected tool names: {tool_names}"

        result = await session.call_tool(
            "lvdcp_inspect",
            arguments={"path": str(tmp_path)},
        )
        assert result.content, "lvdcp_inspect returned no content"
