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

from mcp.server.fastmcp import FastMCP

from .registry import SessionRegistry

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
    # Placeholder - implementation in cic-ir7
    return {
        "error": "Not yet implemented - see task cic-ir7",
        "project_path": project_path,
        "session_name": session_name,
        "layout": layout,
    }


@mcp.tool()
async def list_sessions() -> list[dict]:
    """
    List all managed Claude Code sessions.

    Returns information about each session including its ID, name,
    project path, and current status.

    Returns:
        List of session info dicts
    """
    # Placeholder - implementation in cic-v98
    return [{"error": "Not yet implemented - see task cic-v98"}]


@mcp.tool()
async def send_message(
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
    # Placeholder - implementation in cic-3tv
    return {
        "error": "Not yet implemented - see task cic-3tv",
        "session_id": session_id,
        "message": message[:50] + "..." if len(message) > 50 else message,
    }


@mcp.tool()
async def get_response(
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
    # Placeholder - implementation in cic-f0j
    return {
        "error": "Not yet implemented - see task cic-f0j",
        "session_id": session_id,
    }


@mcp.tool()
async def get_session_status(session_id: str) -> dict:
    """
    Get detailed status of a Claude Code session.

    Returns comprehensive information including terminal screen content,
    conversation statistics, and processing state.

    Args:
        session_id: ID of the target session

    Returns:
        Dict with detailed session status
    """
    # Placeholder - implementation in cic-o7m
    return {
        "error": "Not yet implemented - see task cic-o7m",
        "session_id": session_id,
    }


@mcp.tool()
async def close_session(
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
    # Placeholder - implementation in cic-kiu
    return {
        "error": "Not yet implemented - see task cic-kiu",
        "session_id": session_id,
        "force": force,
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
