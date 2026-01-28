"""
Wait idle workers tool.

Provides wait_idle_workers for blocking until workers become idle.
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..idle_detection import (
    wait_for_all_idle as wait_for_all_idle_impl,
    wait_for_any_idle as wait_for_any_idle_impl,
    SessionInfo,
)
from ..registry import SessionStatus
from ..utils import error_response, HINTS


def register_tools(mcp: FastMCP) -> None:
    """Register wait_idle_workers tool on the MCP server."""

    @mcp.tool()
    async def wait_idle_workers(
        ctx: Context[ServerSession, "AppContext"],
        session_ids: list[str],
        mode: str = "all",
        timeout: float = 600.0,
        poll_interval: float = 2.0,
    ) -> dict:
        """
        Wait for worker sessions to become idle.

        Unified tool for waiting on one or more workers. Supports two modes:
        - "all": Wait until ALL workers are idle (default, for fan-out/fan-in)
        - "any": Return as soon as ANY worker becomes idle (for pipelines)

        Args:
            session_ids: List of session IDs to wait on (accepts 1 or more).
                Accepts internal IDs, terminal IDs, or worker names.
            mode: "all" or "any" - default "all"
            timeout: Maximum seconds to wait (default 10 minutes)
            poll_interval: Seconds between checks (default 2)

        Returns:
            Dict with:
                - session_ids: The session IDs that were requested
                - idle_session_ids: List of sessions that are idle
                - all_idle: Whether all sessions are idle
                - waiting_on: Sessions still working (if timed out)
                - mode: The mode used
                - waited_seconds: How long we waited
                - timed_out: Whether we hit the timeout
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Validate inputs
        if not session_ids:
            return error_response(
                "session_ids is required and must contain at least one session ID",
                hint=HINTS["registry_empty"],
            )

        # Validate mode
        if mode not in ("all", "any"):
            return error_response(
                f"Invalid mode: {mode}. Must be 'all' or 'any'",
            )

        # Look up sessions and build SessionInfo list
        # Uses resolve() to accept internal ID, terminal ID, or name
        session_infos = []
        missing_sessions = []
        missing_jsonl = []

        for session_id in session_ids:
            session = registry.resolve(session_id)
            if not session:
                missing_sessions.append(session_id)
                continue

            jsonl_path = session.get_jsonl_path()
            if not jsonl_path:
                missing_jsonl.append(session_id)
                continue

            session_infos.append(SessionInfo(
                jsonl_path=jsonl_path,
                session_id=session.session_id,  # Must use internal ID to match stop hook marker
                agent_type=session.agent_type,
            ))

        # Report any missing sessions/files
        if missing_sessions:
            return error_response(
                f"Sessions not found: {', '.join(missing_sessions)}",
                hint=HINTS["session_not_found"],
            )

        if missing_jsonl:
            return error_response(
                f"No JSONL files for: {', '.join(missing_jsonl)}",
                hint=HINTS["no_jsonl_file"],
            )

        # Wait based on mode
        if mode == "any":
            result = await wait_for_any_idle_impl(
                sessions=session_infos,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            # Convert to common format
            idle_session_ids = [result["idle_session_id"]] if result["idle_session_id"] else []
            return {
                "session_ids": session_ids,
                "idle_session_ids": idle_session_ids,
                "all_idle": len(idle_session_ids) == len(session_ids),
                "waiting_on": [s for s in session_ids if s not in idle_session_ids],
                "mode": mode,
                "waited_seconds": result["waited_seconds"],
                "timed_out": result["timed_out"],
            }
        else:
            # mode == "all"
            result = await wait_for_all_idle_impl(
                sessions=session_infos,
                timeout=timeout,
                poll_interval=poll_interval,
            )

            # Update statuses for idle sessions
            for session_id in result["idle_session_ids"]:
                registry.update_status(session_id, SessionStatus.READY)

            return {
                "session_ids": session_ids,
                "idle_session_ids": result["idle_session_ids"],
                "all_idle": result["all_idle"],
                "waiting_on": result["waiting_on"],
                "mode": mode,
                "waited_seconds": result["waited_seconds"],
                "timed_out": result["timed_out"],
            }
