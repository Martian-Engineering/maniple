"""
Worker management tools.

Provides list_workers, message_workers, and close_workers for managing
active Claude Code worker sessions.
"""

import asyncio
import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from ..idle_detection import (
    wait_for_all_idle as wait_for_all_idle_impl,
    wait_for_any_idle as wait_for_any_idle_impl,
    SessionInfo,
)
from ..iterm_utils import send_prompt, send_key, close_pane
from ..registry import SessionRegistry, SessionStatus
from ..worktree import WorktreeError, remove_worktree
from ..utils import error_response, HINTS
from .beads import WORKER_MESSAGE_HINT

logger = logging.getLogger("claude-team-mcp")


async def _close_single_worker(
    session,
    session_id: str,
    registry: "SessionRegistry",
    force: bool = False,
) -> dict:
    """
    Close a single worker session.

    Internal helper for close_workers. Handles the actual close logic
    for one session.

    Args:
        session: The ManagedSession object
        session_id: ID of the session to close
        registry: The session registry
        force: If True, force close even if session is busy

    Returns:
        Dict with success status and worktree_cleaned flag
    """
    # Check if busy
    if session.status == SessionStatus.BUSY and not force:
        return {
            "success": False,
            "error": "Session is busy",
            "hint": HINTS["session_busy"],
            "worktree_cleaned": False,
        }

    try:
        # Send Ctrl+C to interrupt any running operation
        await send_key(session.iterm_session, "ctrl-c")
        # TODO(rabsef-bicrym): Programmatically time these actions
        await asyncio.sleep(1.0)

        # Send /exit to quit Claude
        await send_prompt(session.iterm_session, "/exit", submit=True)
        # TODO(rabsef-bicrym): Programmatically time these actions
        await asyncio.sleep(1.0)

        # Clean up worktree if exists (keeps branch alive for cherry-picking)
        worktree_cleaned = False
        if session.worktree_path and session.main_repo_path:
            try:
                remove_worktree(
                    repo_path=session.main_repo_path,
                    worktree_path=session.worktree_path,
                )
                worktree_cleaned = True
            except WorktreeError as e:
                # Log but don't fail the close
                logger.warning(f"Failed to clean up worktree for {session_id}: {e}")

        # Close the iTerm2 pane/window
        await close_pane(session.iterm_session, force=force)

        # Remove from registry
        registry.remove(session_id)

        return {
            "success": True,
            "worktree_cleaned": worktree_cleaned,
        }

    except Exception as e:
        logger.error(f"Failed to close session {session_id}: {e}")
        # Still try to remove from registry
        registry.remove(session_id)
        return {
            "success": True,
            "warning": f"Session removed but cleanup may be incomplete: {e}",
            "worktree_cleaned": False,
        }


def register_tools(mcp: FastMCP) -> None:
    """Register worker management tools on the MCP server."""

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
            if isinstance(item, Exception):
                logger.error(f"Unexpected exception in message_workers: {item}")
                continue
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
                        session_id=sid,
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

    @mcp.tool()
    async def close_workers(
        ctx: Context[ServerSession, "AppContext"],
        session_ids: list[str],
        force: bool = False,
    ) -> dict:
        """
        Close one or more managed Claude Code sessions.

        Gracefully terminates the Claude sessions in parallel and closes
        their iTerm2 panes. All session_ids must exist in the registry.

        Args:
            session_ids: List of session IDs to close (1 or more required)
            force: If True, force close even if sessions are busy

        Returns:
            Dict with:
                - session_ids: List of session IDs that were requested
                - results: Dict mapping session_id to individual result
                - success_count: Number of sessions closed successfully
                - failure_count: Number of sessions that failed to close
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        if not session_ids:
            return error_response(
                "No session_ids provided",
                hint="Provide at least one session_id to close",
            )

        # Validate all sessions exist first (fail fast)
        sessions_to_close = []
        missing_sessions = []

        for sid in session_ids:
            session = registry.resolve(sid)
            if not session:
                missing_sessions.append(sid)
            else:
                sessions_to_close.append((sid, session))

        # If any sessions are missing, fail the entire operation
        if missing_sessions:
            return error_response(
                f"Sessions not found: {', '.join(missing_sessions)}",
                hint=HINTS["session_not_found"],
                session_ids=session_ids,
                missing=missing_sessions,
            )

        # Close all sessions in parallel
        async def close_one(sid: str, session) -> tuple[str, dict]:
            result = await _close_single_worker(session, sid, registry, force)
            return (sid, result)

        tasks = [close_one(sid, session) for sid, session in sessions_to_close]
        parallel_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        results = {}
        for item in parallel_results:
            if isinstance(item, Exception):
                # Shouldn't happen since _close_single_worker catches exceptions
                logger.error(f"Unexpected exception in close_workers: {item}")
                continue
            sid, result = item
            results[sid] = result

        success_count = sum(1 for r in results.values() if r.get("success", False))
        failure_count = len(results) - success_count

        return {
            "session_ids": session_ids,
            "results": results,
            "success_count": success_count,
            "failure_count": failure_count,
        }
