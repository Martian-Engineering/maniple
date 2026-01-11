"""
Message workers tool.

Provides message_workers for sending messages to Claude Code worker sessions.
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..cli_backends.codex import codex_cli
from ..idle_detection import (
    get_codex_thread_id,
    wait_for_all_idle as wait_for_all_idle_impl,
    wait_for_any_idle as wait_for_any_idle_impl,
    SessionInfo,
)
from ..iterm_utils import send_prompt
from ..registry import SessionStatus
from ..utils import error_response, HINTS, WORKER_MESSAGE_HINT

logger = logging.getLogger("claude-team-mcp")


async def _send_to_codex_session(session, message: str) -> dict:
    """
    Send a message to a Codex worker session via resume command.

    Codex doesn't have an interactive mode like Claude. To send follow-up
    messages, we spawn a new `codex exec resume <thread_id>` process.
    The message is piped via stdin using a heredoc.

    This function:
    1. Discovers the thread_id from the previous JSONL output (if not cached)
    2. Creates a new unique JSONL path for this turn's output
    3. Builds and sends the resume command to the terminal
    4. Updates the session's JSONL path for idle detection

    Args:
        session: The ManagedSession for the Codex worker
        message: The message/prompt to send

    Returns:
        Dict with success status and details
    """
    from ..iterm_utils import send_prompt

    # Step 1: Get or discover thread_id
    thread_id = session.codex_thread_id
    if not thread_id and session.codex_jsonl_path:
        thread_id = get_codex_thread_id(session.codex_jsonl_path)
        if thread_id:
            # Cache it for future use
            session.codex_thread_id = thread_id

    if not thread_id:
        return {
            "success": False,
            "error": "Cannot resume Codex session: thread_id not found",
            "hint": "The initial Codex spawn may not have completed or JSONL is missing",
        }

    # Step 2: Create new JSONL path for this turn's output
    # Use a unique suffix to track multiple turns in the same session
    if session.codex_jsonl_path:
        base_dir = session.codex_jsonl_path.parent
        # Generate new path with turn suffix
        turn_id = str(uuid.uuid4())[:8]
        new_jsonl_path = base_dir / f"codex-{session.session_id}-turn-{turn_id}.jsonl"
    else:
        # Fallback: create in temp directory
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "claude-team" / "codex"
        temp_dir.mkdir(parents=True, exist_ok=True)
        turn_id = str(uuid.uuid4())[:8]
        new_jsonl_path = temp_dir / f"codex-{session.session_id}-turn-{turn_id}.jsonl"

    # Step 3: Build the resume command
    # TODO: Determine full_auto from session config (may need to track from spawn)
    resume_cmd = codex_cli.build_resume_command(
        thread_id=thread_id,
        message=message,
        full_auto=True,  # Assume full_auto for workers (matches spawn behavior)
        output_jsonl_path=str(new_jsonl_path),
    )

    # Step 4: Send the command to the terminal
    # The heredoc command needs to be sent line by line or as a whole and submitted
    await send_prompt(session.iterm_session, resume_cmd, submit=True)

    # Step 5: Update session's JSONL path for future idle detection
    session.codex_jsonl_path = new_jsonl_path

    logger.info(
        f"Sent resume command to Codex session {session.session_id} "
        f"(thread_id={thread_id}, output={new_jsonl_path})"
    )

    return {
        "success": True,
        "message_sent": message[:100] + "..." if len(message) > 100 else message,
        "thread_id": thread_id,
        "jsonl_path": str(new_jsonl_path),
    }


async def _wait_for_sessions_idle(
    sessions: list[tuple[str, object]],
    mode: str,
    timeout: float,
    poll_interval: float = 2.0,
) -> dict:
    """
    Wait for sessions to become idle using session.is_idle().

    This unified waiting function works for both Claude and Codex sessions
    by calling session.is_idle() which internally handles agent-specific
    idle detection.

    Args:
        sessions: List of (session_id, ManagedSession) tuples
        mode: "any" or "all"
        timeout: Maximum seconds to wait
        poll_interval: Seconds between checks

    Returns:
        Dict with idle_session_ids, all_idle, timed_out
    """
    import time

    start = time.time()

    while time.time() - start < timeout:
        idle_sessions = []
        working_sessions = []

        for sid, session in sessions:
            if session.is_idle():
                idle_sessions.append(sid)
            else:
                working_sessions.append(sid)

        if mode == "any" and idle_sessions:
            return {
                "idle_session_ids": idle_sessions,
                "all_idle": len(working_sessions) == 0,
                "timed_out": False,
            }
        elif mode == "all" and not working_sessions:
            return {
                "idle_session_ids": idle_sessions,
                "all_idle": True,
                "timed_out": False,
            }

        await asyncio.sleep(poll_interval)

    # Timeout - return final state
    idle_sessions = []
    working_sessions = []
    for sid, session in sessions:
        if session.is_idle():
            idle_sessions.append(sid)
        else:
            working_sessions.append(sid)

    return {
        "idle_session_ids": idle_sessions,
        "all_idle": len(working_sessions) == 0,
        "timed_out": True,
    }


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

                # Handle Codex workers differently - use resume command
                if session.agent_type == "codex":
                    result = await _send_to_codex_session(session, message_with_hint)
                    return (sid, result)

                # For Claude workers, send the message directly to the terminal
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

            # Separate sessions by agent type for different idle detection methods
            claude_sessions = []
            codex_sessions = []
            for sid, session in valid_sessions:
                if session.agent_type == "codex":
                    codex_sessions.append((sid, session))
                else:
                    # Claude sessions use JSONL-based SessionInfo
                    jsonl_path = session.get_jsonl_path()
                    if jsonl_path:
                        claude_sessions.append((sid, session, jsonl_path))

            # Build session infos for Claude sessions
            session_infos = [
                SessionInfo(jsonl_path=jsonl_path, session_id=sid)
                for sid, session, jsonl_path in claude_sessions
            ]

            # For mixed sessions, use unified polling via session.is_idle()
            if codex_sessions or not session_infos:
                # Use session.is_idle() which handles both Claude and Codex
                idle_result = await _wait_for_sessions_idle(
                    sessions=[(sid, session) for sid, session in valid_sessions],
                    mode=wait_mode,
                    timeout=timeout,
                    poll_interval=2.0,
                )
                result["idle_session_ids"] = idle_result.get("idle_session_ids", [])
                result["all_idle"] = idle_result.get("all_idle", False)
                result["timed_out"] = idle_result.get("timed_out", False)
            elif session_infos:
                # Pure Claude sessions - use optimized Claude-specific waiting
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

            # Update status for idle sessions (applies to both paths)
            for sid in result.get("idle_session_ids", []):
                registry.update_status(sid, SessionStatus.READY)
        else:
            # No waiting - mark sessions as ready immediately
            for sid, session in valid_sessions:
                if results.get(sid, {}).get("success"):
                    registry.update_status(sid, SessionStatus.READY)

        return result
