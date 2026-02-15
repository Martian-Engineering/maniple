"""
Annotate worker tool.

Provides annotate_worker for adding coordinator notes to workers.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..utils import error_response, get_session_or_error


def register_tools(mcp: FastMCP) -> None:
    """Register annotate_worker tool on the MCP server."""

    @mcp.tool()
    async def annotate_worker(
        ctx: Context[ServerSession, "AppContext"],
        session_id: str,
        badge: str,
    ) -> dict:
        """
        Add a coordinator badge to a worker.

        Coordinators use this to track what task each worker is assigned to.
        These badges appear in list_workers output.

        ⚠️ **IMPORTANT**: This updates metadata only and does NOT send any message
        to the worker. The worker will not be notified. Use `message_workers` to
        send actual instructions to workers.

        Use this to:
        - Update your tracking notes after spawning
        - Track what phase of work a worker is in
        - Add context visible in list_workers output

        Args:
            session_id: The session to annotate.
                Accepts internal IDs, terminal IDs, or worker names.
            badge: Note about what this worker is working on (coordinator
                tracking only - worker does not receive this)

        Returns:
            Confirmation that the badge was saved
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry
        if not badge:
            return error_response("'badge' is required")

        # Look up session (accepts internal ID, terminal ID, or name)
        session = get_session_or_error(registry, session_id)
        if isinstance(session, dict):
            return session  # Error response

        session.coordinator_badge = badge
        session.update_activity()

        return {
            "success": True,
            "session_id": session_id,
            "badge": badge,
            "message": "Badge saved",
        }
