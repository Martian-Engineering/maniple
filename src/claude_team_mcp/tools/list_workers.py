"""
List workers tool.

Provides list_workers for viewing all managed Claude Code sessions.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..registry import SessionStatus
from ..utils import error_response


def register_tools(mcp: FastMCP) -> None:
    """Register list_workers tool on the MCP server."""

    @mcp.tool()
    async def list_workers(
        ctx: Context[ServerSession, "AppContext"],
        status_filter: str | None = None,
    ) -> dict:
        """
        List all managed Claude Code sessions.

        Returns information about each session including its ID, name,
        project path, and current status. Results are sorted by creation time.

        Args:
            status_filter: Optional filter by status - "ready", "busy", "spawning", "closed"

        Returns:
            Dict with:
                - workers: List of session info dicts
                - count: Number of workers returned
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Get sessions, optionally filtered by status
        if status_filter:
            try:
                status = SessionStatus(status_filter)
                sessions = registry.list_by_status(status)
            except ValueError:
                valid_statuses = [s.value for s in SessionStatus]
                return error_response(
                    f"Invalid status filter: {status_filter}",
                    hint=f"Valid statuses are: {', '.join(valid_statuses)}",
                )
        else:
            sessions = registry.list_all()

        # Sort by created_at
        sessions = sorted(sessions, key=lambda s: s.created_at)

        # Convert to dicts and add message count + idle status
        workers = []
        for session in sessions:
            info = session.to_dict()
            # Try to get conversation stats
            state = session.get_conversation_state()
            if state:
                info["message_count"] = state.message_count
            # Check idle using stop hook detection
            info["is_idle"] = session.is_idle()
            workers.append(info)

        return {
            "workers": workers,
            "count": len(workers),
        }
