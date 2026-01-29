"""
Claude Team MCP Server

FastMCP-based server for managing multiple Claude Code sessions via terminal backends.
Allows a "manager" Claude Code session to spawn and coordinate multiple
"worker" Claude Code sessions.
"""

import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from claude_team.poller import WorkerPoller

from .registry import SessionRegistry
from .terminal_backends import ItermBackend, TerminalBackend, TmuxBackend, select_backend_id
from .tools import register_all_tools
from .utils import error_response, HINTS

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("claude-team-mcp")
# Add file handler for debugging
_fh = logging.FileHandler("/tmp/claude-team-debug.log")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(_fh)
logging.getLogger().addHandler(_fh)  # Also capture root logger
logger.info("=== Claude Team MCP Server Starting ===")


# =============================================================================
# Singleton Registry (persists across MCP sessions for HTTP mode)
# =============================================================================

_global_registry: SessionRegistry | None = None
_global_poller: WorkerPoller | None = None


def get_global_registry() -> SessionRegistry:
    """Get or create the global singleton registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = SessionRegistry()
        logger.info("Created global singleton registry")
    return _global_registry


def get_global_poller(registry: SessionRegistry) -> WorkerPoller:
    """Get or create the global singleton poller."""
    global _global_poller
    if _global_poller is None:
        _global_poller = WorkerPoller(registry)
        logger.info("Created global singleton poller")
    return _global_poller


# =============================================================================
# Application Context
# =============================================================================


@dataclass
class AppContext:
    """
    Application context shared across all tool invocations.

    Maintains the terminal backend and registry of managed sessions.
    This is the persistent state that makes the MCP server useful.
    """

    terminal_backend: TerminalBackend
    registry: SessionRegistry


# =============================================================================
# Lifespan Management
# =============================================================================


async def refresh_iterm_connection() -> ItermBackend:
    """
    Create a fresh iTerm2 connection and backend.

    The iTerm2 Python API uses websockets with ping_interval=None, meaning
    connections can go stale without any keepalive mechanism. This function
    creates a new connection when needed.

    Returns:
        ItermBackend with a fresh connection and app

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
        return ItermBackend(connection, app)
    except Exception as e:
        logger.error(f"Failed to refresh iTerm2 connection: {e}")
        raise RuntimeError("Could not connect to iTerm2") from e


async def ensure_connection(app_ctx: "AppContext") -> TerminalBackend:
    """
    Ensure we have a working terminal backend, refreshing if stale.

    The iTerm2 websocket connection can go stale due to lack of keepalive
    (ping_interval=None in the iterm2 library). This function tests the
    connection and refreshes it if needed.

    For non-iTerm backends (e.g., tmux), this simply returns the backend.

    Args:
        app_ctx: The application context containing the backend

    Returns:
        TerminalBackend - either existing or refreshed
    """
    backend = app_ctx.terminal_backend
    if not isinstance(backend, ItermBackend):
        return backend

    from iterm2.app import async_get_app

    connection = backend.connection
    app = backend.app

    # Test if connection is still alive by trying a simple operation
    try:
        # async_get_app is a lightweight call that tests the connection
        refreshed_app = await async_get_app(connection)
        if refreshed_app is not None:
            if refreshed_app is not app:
                backend = ItermBackend(connection, refreshed_app)
                app_ctx.terminal_backend = backend
            return backend
        # App is None, need to refresh
        raise RuntimeError("App is None, refreshing connection")
    except Exception as e:
        logger.warning(f"iTerm2 connection appears stale ({e}), refreshing...")
        # Connection is dead, create a new one
        backend = await refresh_iterm_connection()
        app_ctx.terminal_backend = backend
        return backend


@asynccontextmanager
async def app_lifespan(
    server: FastMCP,
    enable_poller: bool = False,
) -> AsyncIterator[AppContext]:
    """
    Manage terminal backend connection lifecycle.

    Connects to the terminal backend on startup and maintains the connection
    for the duration of the server's lifetime.

    Note: The iTerm2 Python API uses websockets with ping_interval=None,
    meaning connections can go stale. Individual tool functions should use
    ensure_connection() before making terminal backend calls that use the
    connection directly.
    """
    logger.info("Claude Team MCP Server starting...")

    backend_id = select_backend_id()
    logger.info("Selecting terminal backend: %s", backend_id)

    if backend_id == "tmux":
        backend: TerminalBackend = TmuxBackend()
    elif backend_id == "iterm":
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
        backend = ItermBackend(connection, app)
    else:
        raise RuntimeError(f"Unknown terminal backend: {backend_id}")

    # Create application context with singleton registry (persists across sessions).
    ctx = AppContext(
        terminal_backend=backend,
        registry=get_global_registry(),
    )
    poller: WorkerPoller | None = None
    if enable_poller:
        poller = get_global_poller(ctx.registry)
        poller.start()

    try:
        yield ctx
    finally:
        # Keep the global poller running across per-session lifespans.
        # Cleanup: close any remaining sessions gracefully
        logger.info("Claude Team MCP Server shutting down...")
        if ctx.registry.count() > 0:
            logger.info(f"Cleaning up {ctx.registry.count()} managed session(s)...")
        logger.info("Shutdown complete")


# =============================================================================
# FastMCP Server Factory
# =============================================================================


def create_mcp_server(
    host: str = "127.0.0.1",
    port: int = 8766,
    enable_poller: bool = False,
) -> FastMCP:
    """Create and configure the FastMCP server instance."""
    server = FastMCP(
        "Claude Team Manager",
        lifespan=functools.partial(app_lifespan, enable_poller=enable_poller),
        host=host,
        port=port,
    )
    # Register all tools from the tools package
    register_all_tools(server, ensure_connection)
    return server


# Default server instance for stdio mode (backwards compatibility)
mcp = create_mcp_server()


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

    Returns the visible text in the terminal pane for the specified session.
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
        screen_text = await app_ctx.terminal_backend.read_screen_text(session.terminal_session)
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


def run_server(transport: str = "stdio", port: int = 8766):
    """
    Run the MCP server.

    Args:
        transport: Transport mode - "stdio" or "streamable-http"
        port: Port for HTTP transport (default 8766)
    """
    if transport == "streamable-http":
        logger.info(f"Starting Claude Team MCP Server (HTTP on port {port})...")
        # Create server with configured port for HTTP mode
        server = create_mcp_server(host="127.0.0.1", port=port, enable_poller=True)
        server.run(transport="streamable-http")
    else:
        logger.info("Starting Claude Team MCP Server (stdio)...")
        mcp.run(transport="stdio")


def main():
    """CLI entry point with argument parsing."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Claude Team MCP Server")
    # Global server options apply when no subcommand is provided.
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run in HTTP mode (streamable-http) instead of stdio",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Port for HTTP mode (default: 8766)",
    )
    # Config subcommands for reading/writing ~/.claude-team/config.json.
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser(
        "config",
        help="Manage claude-team configuration",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    init_parser = config_subparsers.add_parser(
        "init",
        help="Write default config to disk",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config file",
    )

    config_subparsers.add_parser(
        "show",
        help="Show effective config (file + env overrides)",
    )

    get_parser = config_subparsers.add_parser(
        "get",
        help="Get a single config value by dotted path",
    )
    get_parser.add_argument("key", help="Dotted config key (e.g. defaults.layout)")

    set_parser = config_subparsers.add_parser(
        "set",
        help="Set a single config value by dotted path",
    )
    set_parser.add_argument("key", help="Dotted config key (e.g. defaults.layout)")
    set_parser.add_argument("value", help="Value to set")

    args = parser.parse_args()

    # Handle config subcommands early to avoid starting the server.
    if args.command == "config":
        from .config import ConfigError
        from .config_cli import (
            format_value_json,
            get_config_value,
            init_config,
            render_config_json,
            set_config_value,
        )

        try:
            if args.config_command == "init":
                path = init_config(force=args.force)
                print(path)
            elif args.config_command == "show":
                print(render_config_json())
            elif args.config_command == "get":
                value = get_config_value(args.key)
                print(format_value_json(value))
            elif args.config_command == "set":
                set_config_value(args.key, args.value)
            else:
                config_parser.print_help()
                raise SystemExit(2)
        except ConfigError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    # Default behavior: run the MCP server.
    if args.http:
        run_server(transport="streamable-http", port=args.port)
    else:
        run_server(transport="stdio")


if __name__ == "__main__":
    main()
