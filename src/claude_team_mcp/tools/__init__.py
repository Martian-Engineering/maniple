"""
Claude Team MCP tools package.

Provides all tool registration functions for the MCP server.
"""

from mcp.server.fastmcp import FastMCP

from . import adopt_worker
from . import annotate_worker
from . import issue_tracker_help
from . import check_idle_workers
from . import close_workers
from . import discover_workers
from . import examine_worker
from . import list_workers
from . import list_worktrees
from . import message_workers
from . import poll_worker_changes
from . import read_worker_logs
from . import spawn_workers
from . import wait_idle_workers


def register_all_tools(mcp: FastMCP, ensure_connection) -> None:
    """
    Register all tools on the MCP server.

    Args:
        mcp: The FastMCP server instance
        ensure_connection: Function to ensure terminal backend is alive
    """
    # Tools that don't need ensure_connection
    annotate_worker.register_tools(mcp)
    issue_tracker_help.register_tools(mcp)
    check_idle_workers.register_tools(mcp)
    close_workers.register_tools(mcp)
    examine_worker.register_tools(mcp)
    list_workers.register_tools(mcp)
    list_worktrees.register_tools(mcp)
    message_workers.register_tools(mcp)
    poll_worker_changes.register_tools(mcp)
    read_worker_logs.register_tools(mcp)
    wait_idle_workers.register_tools(mcp)

    # Tools that need ensure_connection for terminal backend operations
    adopt_worker.register_tools(mcp, ensure_connection)
    discover_workers.register_tools(mcp, ensure_connection)
    spawn_workers.register_tools(mcp, ensure_connection)


__all__ = [
    "register_all_tools",
]
