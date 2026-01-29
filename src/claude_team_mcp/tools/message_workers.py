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
from ..issue_tracker import detect_issue_tracker
from ..iterm_utils import CODEX_PRE_ENTER_DELAY
from ..registry import SessionStatus
from ..terminal_backends import ItermBackend
from ..utils import build_worker_message_hint, error_response, HINTS

logger = logging.getLogger("claude-team-mcp")


def _compute_prompt_delay(text: str, agent_type: str) -> float:
    """Compute a safe delay before sending Enter for a prompt."""
    line_count = text.count("\n")
    char_count = len(text)
    if line_count > 0:
        paste_delay = min(2.0, 0.1 + (line_count * 0.01) + (char_count / 1000 * 0.05))
    else:
        paste_delay = 0.05
    if agent_type == "codex":
        return max(CODEX_PRE_ENTER_DELAY, paste_delay)
    return paste_delay


async def _send_prompt_for_agent(backend, session, text: str, agent_type: str) -> None:
    """Send a prompt through the active terminal backend."""
    if isinstance(backend, ItermBackend):
        await backend.send_prompt_for_agent(
            session,
            text,
            agent_type=agent_type,
            submit=True,
        )
        return
    await backend.send_text(session, text)
    await asyncio.sleep(_compute_prompt_delay(text, agent_type))
    await backend.send_key(session, "enter")


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
        backend = app_ctx.terminal_backend

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

                # Append tracker-specific hint so workers know how to log progress.
                tracker_path = (
                    str(session.main_repo_path)
                    if session.main_repo_path is not None
                    else session.project_path
                )
                tracker_backend = detect_issue_tracker(tracker_path)
                message_with_hint = message + build_worker_message_hint(tracker_backend)

                # Send the message using agent-specific input handling.
                # Codex needs a longer pre-Enter delay than Claude.
                await _send_prompt_for_agent(
                    backend,
                    session.terminal_session,
                    message_with_hint,
                    session.agent_type,
                )

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
