"""FastMCP server — registers the four lvdcp_* tools and runs via stdio."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from apps.mcp.tools import (
    lvdcp_explain as _lvdcp_explain,
)
from apps.mcp.tools import (
    lvdcp_inspect as _lvdcp_inspect,
)
from apps.mcp.tools import (
    lvdcp_neighbors as _lvdcp_neighbors,
)
from apps.mcp.tools import (
    lvdcp_pack as _lvdcp_pack,
)
from apps.mcp.tools import (
    lvdcp_scan as _lvdcp_scan,
)
from apps.mcp.tools import (
    lvdcp_status as _lvdcp_status,
)

mcp = FastMCP(
    "lvdcp",
    instructions=(
        "LV_DCP context tools. Call lvdcp_pack before answering architectural "
        "or edit questions about a Python project — it returns 2-20 KB of "
        "ranked relevant files much cheaper than grep-walking the repo.\n\n"
        "IMPORTANT: You MUST call lvdcp_pack BEFORE using Grep or Read tools "
        "when working in a project that has .context/cache.db. The pack is "
        "1000x cheaper than grep-walking and already knows the dependency graph. "
        "Do NOT skip this step — it saves tokens and gives better results."
    ),
)

# Register tools — delegating to the implementations in tools.py
mcp.tool()(_lvdcp_scan)
mcp.tool()(_lvdcp_pack)
mcp.tool()(_lvdcp_inspect)
mcp.tool()(_lvdcp_explain)
mcp.tool()(_lvdcp_status)
mcp.tool()(_lvdcp_neighbors)


def run_stdio() -> None:
    """Run the server with stdio transport — used by `ctx mcp serve`."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
