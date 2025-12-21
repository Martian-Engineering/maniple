"""
Claude Team MCP tools package.

Provides all tool registration functions for the MCP server.
"""

from mcp.server.fastmcp import FastMCP

from . import beads
from . import discovery
from . import idle
from . import logs
from . import spawn
from . import workers
from . import worktrees


def register_all_tools(mcp: FastMCP, ensure_connection) -> None:
    """
    Register all tools on the MCP server.

    Args:
        mcp: The FastMCP server instance
        ensure_connection: Function to ensure iTerm2 connection is alive
    """
    # Tools that don't need ensure_connection
    beads.register_tools(mcp)
    idle.register_tools(mcp)
    logs.register_tools(mcp)
    workers.register_tools(mcp)
    worktrees.register_tools(mcp)

    # Tools that need ensure_connection for iTerm2 operations
    discovery.register_tools(mcp, ensure_connection)
    spawn.register_tools(mcp, ensure_connection)


__all__ = [
    "register_all_tools",
    "beads",
    "discovery",
    "idle",
    "logs",
    "spawn",
    "workers",
    "worktrees",
]
