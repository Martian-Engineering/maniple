"""
Claude Team MCP Server

FastMCP-based server for managing multiple Claude Code sessions via iTerm2.
Allows a "manager" Claude Code session to spawn and coordinate multiple
"worker" Claude Code sessions.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iterm2.app import App as ItermApp
    from iterm2.connection import Connection as ItermConnection

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .iterm_utils import read_screen_text
from .registry import SessionRegistry
from .tools import register_all_tools
from .utils import error_response, HINTS

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

    iterm_connection: "ItermConnection"
    iterm_app: "ItermApp"
    registry: SessionRegistry


# =============================================================================
# Lifespan Management
# =============================================================================


async def refresh_iterm_connection() -> tuple["ItermConnection", "ItermApp"]:
    """
    Create a fresh iTerm2 connection.

    The iTerm2 Python API uses websockets with ping_interval=None, meaning
    connections can go stale without any keepalive mechanism. This function
    creates a new connection when needed.

    Returns:
        Tuple of (connection, app)

    Raises:
        RuntimeError: If connection fails
    """
    from iterm2.app import async_get_app
    from iterm2.connection import Connection

    logger.debug("Creating fresh iTerm2 connection...")
    try:
        connection = await Connection.async_create()
        app = await async_get_app(connection)
        if app is None:
            raise RuntimeError("Could not get iTerm2 app")
        logger.debug("Fresh iTerm2 connection established")
        return connection, app
    except Exception as e:
        logger.error(f"Failed to refresh iTerm2 connection: {e}")
        raise RuntimeError("Could not connect to iTerm2") from e


async def ensure_connection(app_ctx: "AppContext") -> tuple["ItermConnection", "ItermApp"]:
    """
    Ensure we have a working iTerm2 connection, refreshing if stale.

    The iTerm2 websocket connection can go stale due to lack of keepalive
    (ping_interval=None in the iterm2 library). This function tests the
    connection and refreshes it if needed.

    Args:
        app_ctx: The application context containing connection and app

    Returns:
        Tuple of (connection, app) - either existing or refreshed
    """
    from iterm2.app import async_get_app

    connection = app_ctx.iterm_connection
    app = app_ctx.iterm_app

    # Test if connection is still alive by trying a simple operation
    try:
        # async_get_app is a lightweight call that tests the connection
        refreshed_app = await async_get_app(connection)
        if refreshed_app is not None:
            return connection, refreshed_app
        # App is None, need to refresh
        raise RuntimeError("App is None, refreshing connection")
    except Exception as e:
        logger.warning(f"iTerm2 connection appears stale ({e}), refreshing...")
        # Connection is dead, create a new one
        connection, app = await refresh_iterm_connection()
        # Update the context with fresh connection
        app_ctx.iterm_connection = connection
        app_ctx.iterm_app = app
        return connection, app


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Manage iTerm2 connection lifecycle.

    Connects to iTerm2 on startup and maintains the connection
    for the duration of the server's lifetime.

    Note: The iTerm2 Python API uses websockets with ping_interval=None,
    meaning connections can go stale. Individual tool functions should use
    ensure_connection() before making iTerm2 API calls that use the
    connection directly.
    """
    logger.info("Claude Team MCP Server starting...")

    # Import iterm2 here to fail fast if not available
    try:
        from iterm2.app import async_get_app
        from iterm2.connection import Connection
    except ImportError as e:
        logger.error(
            "iterm2 package not found. Install with: uv add iterm2\n"
            "Also enable: iTerm2 → Preferences → General → Magic → Enable Python API"
        )
        raise RuntimeError("iterm2 package required") from e

    # Connect to iTerm2
    logger.info("Connecting to iTerm2...")
    try:
        connection = await Connection.async_create()
        app = await async_get_app(connection)
        if app is None:
            raise RuntimeError("Could not get iTerm2 app")
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

# Register all tools from the tools package
register_all_tools(mcp, ensure_connection)


# =============================================================================
# MCP Resources
# =============================================================================


@mcp.resource("sessions://list")
async def resource_sessions(ctx: Context[ServerSession, AppContext]) -> list[dict]:
    """
    List all managed Claude Code sessions.

    Returns a list of session summaries including ID, name, project path,
    status, and conversation stats if available. This is a read-only
    resource alternative to the list_workers tool.
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    sessions = registry.list_all()
    results = []

    for session in sessions:
        info = session.to_dict()
        # Add conversation stats if JSONL is available
        state = session.get_conversation_state()
        if state:
            info["message_count"] = state.message_count
        # Check idle using stop hook detection
        info["is_idle"] = session.is_idle()
        results.append(info)

    return results


@mcp.resource("sessions://{session_id}/status")
async def resource_session_status(
    session_id: str, ctx: Context[ServerSession, AppContext]
) -> dict:
    """
    Get detailed status of a specific Claude Code session.

    Returns comprehensive information including session metadata,
    conversation statistics, and processing state. Use the /screen
    resource to get terminal screen content.

    Args:
        session_id: ID of the target session
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    result = session.to_dict()

    # Get conversation stats from JSONL
    stats = session.get_conversation_stats()
    result["conversation_stats"] = stats
    result["message_count"] = stats["total_messages"] if stats else 0

    # Check idle using stop hook detection
    result["is_idle"] = session.is_idle()

    return result


@mcp.resource("sessions://{session_id}/screen")
async def resource_session_screen(
    session_id: str, ctx: Context[ServerSession, AppContext]
) -> dict:
    """
    Get the current terminal screen content for a session.

    Returns the visible text in the iTerm2 pane for the specified session.
    Useful for checking what Claude is currently displaying or doing.

    Args:
        session_id: ID of the target session
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    try:
        screen_text = await read_screen_text(session.iterm_session)
        # Get non-empty lines
        lines = [line for line in screen_text.split("\n") if line.strip()]

        return {
            "session_id": session_id,
            "screen_content": screen_text,
            "screen_preview": "\n".join(lines[-15:]) if lines else "",
            "line_count": len(lines),
            "is_responsive": True,
        }
    except Exception as e:
        return error_response(
            f"Could not read screen: {e}",
            hint=HINTS["iterm_connection"],
            session_id=session_id,
            is_responsive=False,
        )


# =============================================================================
# Server Entry Point
# =============================================================================


def run_server():
    """Run the MCP server with stdio transport."""
    logger.info("Starting Claude Team MCP Server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
