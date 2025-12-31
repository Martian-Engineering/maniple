"""
Annotate worker tool.

Provides annotate_worker for adding coordinator notes to workers.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..utils import get_session_or_error


def register_tools(mcp: FastMCP) -> None:
    """Register annotate_worker tool on the MCP server."""

    @mcp.tool()
    async def annotate_worker(
        ctx: Context[ServerSession, "AppContext"],
        session_id: str,
        annotation: str,
    ) -> dict:
        """
        Add a coordinator annotation to a worker.

        Coordinators use this to track what task each worker is assigned to.
        These annotations appear in list_workers output.

        Args:
            session_id: The session to annotate.
                Accepts internal IDs, terminal IDs, or worker names.
            annotation: Note about what this worker is working on

        Returns:
            Confirmation that the annotation was saved
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Look up session (accepts internal ID, terminal ID, or name)
        session = get_session_or_error(registry, session_id)
        if isinstance(session, dict):
            return session  # Error response

        session.coordinator_annotation = annotation
        session.update_activity()

        return {
            "success": True,
            "session_id": session_id,
            "annotation": annotation,
            "message": "Annotation saved",
        }
