"""
Check idle workers tool.

Provides check_idle_workers for quick non-blocking idle status checks.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..registry import SessionStatus
from ..utils import error_response, HINTS


def register_tools(mcp: FastMCP) -> None:
    """Register check_idle_workers tool on the MCP server."""

    @mcp.tool()
    async def check_idle_workers(
        ctx: Context[ServerSession, "AppContext"],
        session_ids: list[str],
    ) -> dict:
        """
        Check if worker sessions are idle (finished responding).

        Quick non-blocking poll that checks current idle state for multiple sessions.
        Uses Stop hook detection: when Claude finishes responding, the Stop hook
        fires and logs a marker. If the marker exists with no subsequent messages,
        the worker is idle.

        This is distinct from wait_idle_workers - this returns immediately with
        current state, while wait_idle_workers blocks until sessions become idle.

        Args:
            session_ids: List of session IDs to check (required, accepts 1 or more).
                Accepts internal IDs, terminal IDs, or worker names.

        Returns:
            Dict with:
                - session_ids: The input session IDs
                - idle: Dict mapping session_id to idle status (bool)
                - all_idle: Whether all sessions are idle
                - idle_count: Number of idle sessions
                - busy_count: Number of busy sessions
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        if not session_ids:
            return error_response(
                "No session_ids provided",
                hint="Provide at least one session_id to check",
            )

        # Validate all sessions exist first
        missing_sessions = []
        for session_id in session_ids:
            session = registry.resolve(session_id)
            if not session:
                missing_sessions.append(session_id)

        if missing_sessions:
            return error_response(
                f"Sessions not found: {', '.join(missing_sessions)}",
                hint=HINTS["session_not_found"],
            )

        # Check idle status for each session
        idle_results: dict[str, bool] = {}

        for session_id in session_ids:
            session = registry.resolve(session_id)
            # Already validated above, so session should never be None
            if session is None:
                continue  # Should never happen, but satisfies type checker
            idle = session.is_idle()
            idle_results[session_id] = idle

            # Update session status if idle
            if idle:
                registry.update_status(session_id, SessionStatus.READY)

        # Compute summary stats
        idle_count = sum(1 for is_idle in idle_results.values() if is_idle)
        busy_count = len(idle_results) - idle_count
        all_idle = idle_count == len(session_ids)

        return {
            "session_ids": session_ids,
            "idle": idle_results,
            "all_idle": all_idle,
            "idle_count": idle_count,
            "busy_count": busy_count,
        }
