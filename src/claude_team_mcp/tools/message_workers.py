"""
Message workers tool.

Provides message_workers for sending messages to Claude Code worker sessions.
"""

import asyncio
import logging
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
from ..iterm_utils import send_prompt
from ..registry import SessionStatus
from ..utils import error_response, HINTS, WORKER_MESSAGE_HINT

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP) -> None:
    """Register message_workers tool on the MCP server."""

    @mcp.tool()
    async def message_workers(
        ctx: Context[ServerSession, "AppContext"],
        session_ids: list[str],
        message: str,
        wait_mode: str = "none",
        timeout: float = 600.0,
    ) -> dict:
        """
        Send a message to one or more Claude Code worker sessions.

        Sends the same message to all specified sessions in parallel and optionally
        waits for workers to finish responding. This is the unified tool for worker
        communication - use it for both single workers and broadcasts.

        To understand what workers have done, use get_conversation_history or
        get_session_status to read their logs - don't rely on response content.

        Args:
            session_ids: List of session IDs to send the message to (1 or more).
                Accepts internal IDs, terminal IDs, or worker names.
            message: The prompt/message to send to all sessions
            wait_mode: How to wait for workers:
                - "none": Fire and forget, return immediately (default)
                - "any": Wait until at least one worker is idle, then return
                - "all": Wait until all workers are idle, then return
            timeout: Maximum seconds to wait (only used if wait_mode != "none")

        Returns:
            Dict with:
                - success: True if all messages were sent successfully
                - session_ids: List of session IDs that were targeted
                - results: Dict mapping session_id to individual result
                - idle_session_ids: Sessions that are idle (only if wait_mode != "none")
                - all_idle: Whether all sessions are idle (only if wait_mode != "none")
                - timed_out: Whether the wait timed out (only if wait_mode != "none")
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Validate wait_mode
        if wait_mode not in ("none", "any", "all"):
            return error_response(
                f"Invalid wait_mode: {wait_mode}. Must be 'none', 'any', or 'all'",
            )

        if not session_ids:
            return error_response(
                "No session_ids provided",
                hint=HINTS["registry_empty"],
            )

        # Validate all sessions exist first (fail fast if any session is invalid)
        # Uses resolve() to accept internal ID, terminal ID, or name
        missing_sessions = []
        valid_sessions = []

        for sid in session_ids:
            session = registry.resolve(sid)
            if not session:
                missing_sessions.append(sid)
            else:
                valid_sessions.append((sid, session))

        # Report validation errors but continue with valid sessions
        results = {}

        for sid in missing_sessions:
            results[sid] = error_response(
                f"Session not found: {sid}",
                hint=HINTS["session_not_found"],
                success=False,
            )

        if not valid_sessions:
            return {
                "success": False,
                "session_ids": session_ids,
                "results": results,
                **error_response(
                    "No valid sessions to send to",
                    hint=HINTS["session_not_found"],
                ),
            }

        async def send_to_session(sid: str, session) -> tuple[str, dict]:
            """Send message to a single session. Returns tuple of (session_id, result_dict)."""
            try:
                # Update status to busy
                registry.update_status(sid, SessionStatus.BUSY)

                # Append hint about bd_help tool to help workers understand beads
                message_with_hint = message + WORKER_MESSAGE_HINT

                # Send the message to the terminal
                await send_prompt(session.iterm_session, message_with_hint, submit=True)

                return (sid, {
                    "success": True,
                    "message_sent": message[:100] + "..." if len(message) > 100 else message,
                })

            except Exception as e:
                logger.error(f"Failed to send message to {sid}: {e}")
                registry.update_status(sid, SessionStatus.READY)
                return (sid, error_response(
                    str(e),
                    hint=HINTS["iterm_connection"],
                    success=False,
                ))

        # Send to all valid sessions in parallel
        tasks = [send_to_session(sid, session) for sid, session in valid_sessions]
        parallel_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for item in parallel_results:
            if isinstance(item, BaseException):
                logger.error(f"Unexpected exception in message_workers: {item}")
                continue
            # Type narrowing: item is now tuple[str, dict]
            sid, result = item
            results[sid] = result

        # Compute overall success
        success_count = sum(1 for r in results.values() if r.get("success", False))
        overall_success = success_count == len(session_ids)

        result = {
            "success": overall_success,
            "session_ids": session_ids,
            "results": results,
        }

        # Handle waiting if requested
        if wait_mode != "none" and valid_sessions:
            # TODO(rabsef-bicrym): Figure a way to delay this polling without a hard wait.
            # Race condition: We poll for idle immediately after sending, but the JSONL
            # may not have been updated yet with the new user message. The session still
            # appears idle from the previous stop hook, causing us to return prematurely.
            await asyncio.sleep(0.5)

            # Get session infos for idle detection
            session_infos = []
            for sid, session in valid_sessions:
                jsonl_path = session.get_jsonl_path()
                if jsonl_path:
                    session_infos.append(SessionInfo(
                        jsonl_path=jsonl_path,
                        session_id=session.session_id,
                    ))

            if session_infos:
                if wait_mode == "any":
                    idle_result = await wait_for_any_idle_impl(
                        sessions=session_infos,
                        timeout=timeout,
                        poll_interval=2.0,
                    )
                    result["idle_session_ids"] = (
                        [idle_result["idle_session_id"]]
                        if idle_result.get("idle_session_id")
                        else []
                    )
                    result["all_idle"] = False
                    result["timed_out"] = idle_result.get("timed_out", False)
                else:  # wait_mode == "all"
                    idle_result = await wait_for_all_idle_impl(
                        sessions=session_infos,
                        timeout=timeout,
                        poll_interval=2.0,
                    )
                    result["idle_session_ids"] = idle_result.get("idle_session_ids", [])
                    result["all_idle"] = idle_result.get("all_idle", False)
                    result["timed_out"] = idle_result.get("timed_out", False)

                # Update status for idle sessions
                for sid in result.get("idle_session_ids", []):
                    registry.update_status(sid, SessionStatus.READY)
        else:
            # No waiting - mark sessions as ready immediately
            for sid, session in valid_sessions:
                if results.get(sid, {}).get("success"):
                    registry.update_status(sid, SessionStatus.READY)

        return result
