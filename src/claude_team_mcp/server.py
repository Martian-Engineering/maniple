"""
Claude Team MCP Server

FastMCP-based server for managing multiple Claude Code sessions via iTerm2.
Allows a "manager" Claude Code session to spawn and coordinate multiple
"worker" Claude Code sessions.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .iterm_utils import (
    create_window,
    read_screen_text,
    send_prompt,
    split_pane,
    start_claude_in_session,
)
from .registry import SessionRegistry, SessionStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("claude-team-mcp")


# =============================================================================
# Application Context
# =============================================================================


@dataclass
class AppContext:
    """
    Application context shared across all tool invocations.

    Maintains the iTerm2 connection and registry of managed sessions.
    This is the persistent state that makes the MCP server useful.
    """

    iterm_connection: object  # iterm2.Connection
    iterm_app: object  # iterm2.App
    registry: SessionRegistry


# =============================================================================
# Lifespan Management
# =============================================================================


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Manage iTerm2 connection lifecycle.

    Connects to iTerm2 on startup and maintains the connection
    for the duration of the server's lifetime.
    """
    logger.info("Claude Team MCP Server starting...")

    # Import iterm2 here to fail fast if not available
    try:
        import iterm2
    except ImportError as e:
        logger.error(
            "iterm2 package not found. Install with: uv add iterm2\n"
            "Also enable: iTerm2 → Preferences → General → Magic → Enable Python API"
        )
        raise RuntimeError("iterm2 package required") from e

    # Connect to iTerm2
    logger.info("Connecting to iTerm2...")
    try:
        connection = await iterm2.Connection.async_create()
        app = await iterm2.async_get_app(connection)
        logger.info("Connected to iTerm2 successfully")
    except Exception as e:
        logger.error(f"Failed to connect to iTerm2: {e}")
        logger.error("Make sure iTerm2 is running and Python API is enabled")
        raise RuntimeError("Could not connect to iTerm2") from e

    # Create application context with session registry
    ctx = AppContext(
        iterm_connection=connection,
        iterm_app=app,
        registry=SessionRegistry(),
    )

    try:
        yield ctx
    finally:
        # Cleanup: close any remaining sessions gracefully
        logger.info("Claude Team MCP Server shutting down...")
        if ctx.registry.count() > 0:
            logger.info(f"Cleaning up {ctx.registry.count()} managed session(s)...")
        logger.info("Shutdown complete")


# =============================================================================
# FastMCP Server
# =============================================================================

mcp = FastMCP(
    "Claude Team Manager",
    lifespan=app_lifespan,
)


# =============================================================================
# Tool Implementations (Placeholders - will be implemented in separate tasks)
# =============================================================================


@mcp.tool()
async def spawn_session(
    ctx: Context[ServerSession, AppContext],
    project_path: str,
    session_name: str | None = None,
    layout: str = "new_window",
) -> dict:
    """
    Spawn a new Claude Code session in iTerm2.

    Creates a new iTerm2 window or pane, starts Claude Code in it,
    and registers it for management.

    Args:
        project_path: Directory where Claude Code should run
        session_name: Optional friendly name for the session
        layout: How to create the session - "new_window", "split_vertical", or "split_horizontal"

    Returns:
        Dict with session_id, status, and project_path
    """
    app_ctx = ctx.request_context.lifespan_context
    connection = app_ctx.iterm_connection
    app = app_ctx.iterm_app
    registry = app_ctx.registry

    # Validate project path
    resolved_path = os.path.abspath(os.path.expanduser(project_path))
    if not os.path.isdir(resolved_path):
        return {"error": f"Project path does not exist: {resolved_path}"}

    try:
        # Create iTerm2 session based on layout
        if layout == "new_window":
            # Create a new window
            window = await create_window(connection)
            iterm_session = window.current_tab.current_session
        elif layout in ("split_vertical", "split_horizontal"):
            # Split the current window's active session
            current_window = app.current_terminal_window
            if current_window is None:
                # No window exists, create one
                window = await create_window(connection)
                iterm_session = window.current_tab.current_session
            else:
                current_session = current_window.current_tab.current_session
                vertical = layout == "split_vertical"
                iterm_session = await split_pane(current_session, vertical=vertical)
        else:
            return {"error": f"Invalid layout: {layout}. Use: new_window, split_vertical, split_horizontal"}

        # Register the session before starting Claude (so we track it even if startup fails)
        managed = registry.add(
            iterm_session=iterm_session,
            project_path=resolved_path,
            name=session_name,
        )

        # Start Claude Code in the session
        await start_claude_in_session(
            session=iterm_session,
            project_path=resolved_path,
            wait_seconds=4.0,
        )

        # Try to discover the Claude session ID from JSONL
        await asyncio.sleep(1)  # Give Claude a moment to create the session file
        managed.discover_claude_session()

        # Update status to ready
        registry.update_status(managed.session_id, SessionStatus.READY)

        return managed.to_dict()

    except Exception as e:
        logger.error(f"Failed to spawn session: {e}")
        return {"error": str(e)}


@mcp.tool()
async def list_sessions(
    ctx: Context[ServerSession, AppContext],
    status_filter: str | None = None,
) -> list[dict]:
    """
    List all managed Claude Code sessions.

    Returns information about each session including its ID, name,
    project path, and current status.

    Args:
        status_filter: Optional filter by status - "ready", "busy", "spawning", "closed"

    Returns:
        List of session info dicts
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Get sessions, optionally filtered by status
    if status_filter:
        try:
            status = SessionStatus(status_filter)
            sessions = registry.list_by_status(status)
        except ValueError:
            return [{"error": f"Invalid status filter: {status_filter}"}]
    else:
        sessions = registry.list_all()

    # Convert to dicts and add message count if JSONL is available
    results = []
    for session in sessions:
        info = session.to_dict()
        # Try to get conversation stats
        state = session.get_conversation_state()
        if state:
            info["message_count"] = state.message_count
            info["is_processing"] = state.is_processing
        results.append(info)

    return results


@mcp.tool()
async def send_message(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    message: str,
    wait_for_response: bool = False,
    timeout: float = 120.0,
) -> dict:
    """
    Send a message to a managed Claude Code session.

    Injects the message into the specified session's terminal and
    optionally waits for Claude's response.

    Args:
        session_id: ID of the target session (from spawn_session or list_sessions)
        message: The prompt/message to send
        wait_for_response: If True, wait for Claude to finish responding
        timeout: Maximum seconds to wait for response (if wait_for_response=True)

    Returns:
        Dict with success status and optional response content
    """
    from .session_state import wait_for_response as wait_for_resp

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return {"error": f"Session not found: {session_id}"}

    # Check session is ready
    if session.status == SessionStatus.CLOSED:
        return {"error": f"Session is closed: {session_id}"}

    try:
        # Update status to busy
        registry.update_status(session_id, SessionStatus.BUSY)

        # Send the message to the terminal
        await send_prompt(session.iterm_session, message, submit=True)

        result = {
            "success": True,
            "session_id": session_id,
            "message_sent": message[:100] + "..." if len(message) > 100 else message,
        }

        # Optionally wait for response
        if wait_for_response:
            jsonl_path = session.get_jsonl_path()
            if jsonl_path and jsonl_path.exists():
                response = await wait_for_resp(
                    jsonl_path=jsonl_path,
                    timeout=timeout,
                    idle_threshold=2.0,
                )
                if response:
                    result["response"] = response.content
                    result["response_preview"] = (
                        response.content[:500] + "..."
                        if len(response.content) > 500
                        else response.content
                    )
                else:
                    result["response"] = None
                    result["timeout"] = True

        # Update status back to ready
        registry.update_status(session_id, SessionStatus.READY)

        return result

    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        registry.update_status(session_id, SessionStatus.READY)
        return {"error": str(e), "session_id": session_id}


@mcp.tool()
async def get_response(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    wait: bool = True,
    timeout: float = 60.0,
) -> dict:
    """
    Get the latest response from a Claude Code session.

    Reads the session's JSONL file to get the last assistant message.
    Can optionally wait for a response if the session is still processing.

    Args:
        session_id: ID of the target session
        wait: If True, wait for Claude to finish if still processing
        timeout: Maximum seconds to wait

    Returns:
        Dict with status, response content, and metadata
    """
    from .session_state import wait_for_response as wait_for_resp

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return {"error": f"Session not found: {session_id}"}

    jsonl_path = session.get_jsonl_path()
    if not jsonl_path or not jsonl_path.exists():
        return {
            "session_id": session_id,
            "status": session.status.value,
            "error": "No JSONL session file found - Claude may not have started yet",
        }

    # Get current state
    state = session.get_conversation_state()
    if not state:
        return {
            "session_id": session_id,
            "status": session.status.value,
            "error": "Could not parse session state",
        }

    # If wait=True and session appears to be processing, wait for idle
    if wait and state.is_processing:
        response = await wait_for_resp(
            jsonl_path=jsonl_path,
            timeout=timeout,
            idle_threshold=2.0,
        )
        # Refresh state after waiting
        state = session.get_conversation_state()

    # Build response
    last_msg = state.last_assistant_message if state else None

    return {
        "session_id": session_id,
        "status": session.status.value,
        "is_processing": state.is_processing if state else False,
        "last_response": last_msg.content if last_msg else None,
        "last_response_preview": (
            last_msg.content[:500] + "..."
            if last_msg and len(last_msg.content) > 500
            else (last_msg.content if last_msg else None)
        ),
        "message_id": last_msg.uuid if last_msg else None,
        "tool_uses": [t.get("name") for t in (last_msg.tool_uses if last_msg else [])],
        "message_count": state.message_count if state else 0,
    }


@mcp.tool()
async def get_session_status(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
) -> dict:
    """
    Get detailed status of a Claude Code session.

    Returns comprehensive information including terminal screen content,
    conversation statistics, and processing state.

    Args:
        session_id: ID of the target session

    Returns:
        Dict with detailed session status
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return {"error": f"Session not found: {session_id}"}

    result = session.to_dict()

    # Try to read screen content
    try:
        screen_text = await read_screen_text(session.iterm_session)
        # Get last few non-empty lines as preview
        lines = [l for l in screen_text.split("\n") if l.strip()]
        result["screen_preview"] = "\n".join(lines[-10:]) if lines else ""
        result["is_responsive"] = True
    except Exception as e:
        result["screen_preview"] = None
        result["is_responsive"] = False
        result["screen_error"] = str(e)

    # Get conversation stats from JSONL
    state = session.get_conversation_state()
    if state:
        user_msgs = [m for m in state.messages if m.role == "user"]
        assistant_msgs = [m for m in state.messages if m.role == "assistant"]

        result["conversation_stats"] = {
            "total_messages": len(state.messages),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "last_user_prompt": (
                user_msgs[-1].content[:200] + "..."
                if user_msgs and len(user_msgs[-1].content) > 200
                else (user_msgs[-1].content if user_msgs else None)
            ),
            "last_assistant_preview": (
                assistant_msgs[-1].content[:200] + "..."
                if assistant_msgs and len(assistant_msgs[-1].content) > 200
                else (assistant_msgs[-1].content if assistant_msgs else None)
            ),
        }
        result["is_processing"] = state.is_processing
    else:
        result["conversation_stats"] = None
        result["is_processing"] = None

    return result


@mcp.tool()
async def close_session(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    force: bool = False,
) -> dict:
    """
    Close a managed Claude Code session.

    Gracefully terminates the Claude session and optionally closes
    the iTerm2 window/pane.

    Args:
        session_id: ID of the session to close
        force: If True, force close even if session is busy

    Returns:
        Dict with success status
    """
    from .iterm_utils import send_key

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return {"error": f"Session not found: {session_id}"}

    # Check if busy
    if session.status == SessionStatus.BUSY and not force:
        return {
            "error": f"Session is busy. Use force=True to close anyway.",
            "session_id": session_id,
            "status": session.status.value,
        }

    try:
        # Send Ctrl+C to interrupt any running operation
        await send_key(session.iterm_session, "ctrl-c")
        await asyncio.sleep(0.5)

        # Send /exit to quit Claude
        await send_prompt(session.iterm_session, "/exit", submit=True)
        await asyncio.sleep(1.0)

        # Update status
        registry.update_status(session_id, SessionStatus.CLOSED)

        # Remove from registry
        registry.remove(session_id)

        return {
            "success": True,
            "session_id": session_id,
            "message": "Session closed and removed from registry",
        }

    except Exception as e:
        logger.error(f"Failed to close session: {e}")
        # Still try to remove from registry
        registry.update_status(session_id, SessionStatus.CLOSED)
        registry.remove(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "warning": f"Session removed but cleanup may be incomplete: {e}",
        }


# =============================================================================
# Server Entry Point
# =============================================================================


def run_server():
    """Run the MCP server with stdio transport."""
    logger.info("Starting Claude Team MCP Server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
