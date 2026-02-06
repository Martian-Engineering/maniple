"""
Examine worker tool.

Provides examine_worker for getting detailed status of a Claude Code session.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..utils import get_session_or_error


def register_tools(mcp: FastMCP) -> None:
    """Register examine_worker tool on the MCP server."""

    @mcp.tool()
    async def examine_worker(
        ctx: Context[ServerSession, "AppContext"],
        session_id: str,
    ) -> dict:
        """
        Get detailed status of a Claude Code session.

        Returns comprehensive information including conversation statistics
        and processing state. Use conversation_stats.last_assistant_preview
        to see what the worker last said.

        Args:
            session_id: ID of the target session.
                Accepts internal IDs, terminal IDs, or worker names.

        Returns:
            Dict with detailed session status
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Look up session (accepts internal ID, terminal ID, or name)
        session = get_session_or_error(registry, session_id)
        if isinstance(session, dict):
            return session  # Error response

        result = session.to_dict()

        # Get conversation stats from JSONL
        result["conversation_stats"] = session.get_conversation_stats()

        # Check idle using stop hook detection
        result["is_idle"] = session.is_idle()

        return result
