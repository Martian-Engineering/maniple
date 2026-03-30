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

from maniple.events import get_latest_snapshot, prune_event_backups, read_events_since
from maniple.poller import WorkerPoller

from .logging_setup import configure_logging
from .registry import RecoveryReport, SessionRegistry
from .terminal_backends import TerminalBackend, TmuxBackend
from .tools import register_all_tools
from .utils import error_response, HINTS

logger = logging.getLogger("maniple")

EVENT_BACKUP_CAP_MB = 200


# =============================================================================
# Singleton Registry (persists across MCP sessions for HTTP mode)
# =============================================================================

_global_registry: SessionRegistry | None = None
_global_poller: WorkerPoller | None = None
_recovery_attempted: bool = False


def get_global_registry() -> SessionRegistry:
    """Get or create the global singleton registry."""
    global _global_registry
    if _global_registry is None:
        from maniple.paths import resolve_data_dir
        persist_path = resolve_data_dir() / "registry.json"
        _global_registry = SessionRegistry(persist_path=persist_path)
        logger.info("Created global singleton registry (persist_path=%s)", persist_path)
    return _global_registry


def get_global_poller(registry: SessionRegistry) -> WorkerPoller:
    """Get or create the global singleton poller."""
    global _global_poller
    if _global_poller is None:
        _global_poller = WorkerPoller(registry)
        logger.info("Created global singleton poller")
    return _global_poller


def recover_registry(registry: SessionRegistry) -> RecoveryReport | None:
    """
    Attempt to recover session state from the event log.

    Reads the latest snapshot and subsequent events from ~/.maniple/events.jsonl,
    then feeds them into registry.recover_from_events() to seed the registry with
    historical session data.

    Args:
        registry: The SessionRegistry to populate

    Returns:
        RecoveryReport if recovery was performed, None if no events available
    """
    global _recovery_attempted
    _recovery_attempted = True

    # Load persisted registry snapshot (write-through file from last run).
    # This is faster and more reliable than event log recovery for common cases.
    persisted_count = registry.load_persisted()
    if persisted_count:
        logger.info("Loaded %d sessions from persisted registry", persisted_count)

    # Best-effort pruning of rotated backup shards so ~/.maniple doesn't grow
    # without bound. Never touches the live events.jsonl.
    try:
        prune_event_backups(max_total_size_mb=EVENT_BACKUP_CAP_MB, dry_run=False)
    except Exception:
        logger.exception("Failed to prune event log backups")

    # Get the latest snapshot from the event log.
    snapshot = get_latest_snapshot()

    # Parse snapshot timestamp to filter subsequent events.
    # The snapshot dict should contain a 'ts' field with the timestamp.
    since = None
    if snapshot is not None:
        ts_str = snapshot.get("ts")
        if ts_str:
            from datetime import datetime, timezone

            # Normalize Zulu timestamps.
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            try:
                since = datetime.fromisoformat(ts_str)
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
            except ValueError:
                since = None

    # Read events since the snapshot (or all events if no snapshot).
    events = read_events_since(since=since, limit=10000)

    # If no snapshot and no events, nothing to recover.
    if snapshot is None and not events:
        logger.info("No event log data available for recovery")
        return None

    # Perform recovery.
    report = registry.recover_from_events(snapshot, events)
    return report


def is_recovery_attempted() -> bool:
    """Check whether recovery has been attempted this session."""
    return _recovery_attempted


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


async def ensure_connection(app_ctx: "AppContext") -> TerminalBackend:
    """Return the terminal backend. iTerm2 connection management is handled
    by ItermManager (lazy-init inside TmuxBackend)."""
    return app_ctx.terminal_backend


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
    logger.info("Maniple MCP Server starting...")

    # Always use tmux backend. iTerm2 window management is handled by
    # ItermManager (lazy-initialized inside TmuxBackend on first use).
    backend: TerminalBackend = TmuxBackend()
    logger.info("Terminal backend: tmux (iTerm2 windows via ItermManager)")

    # Create application context with singleton registry (persists across sessions).
    ctx = AppContext(
        terminal_backend=backend,
        registry=get_global_registry(),
    )

    # Attempt eager recovery from event log to seed the registry with historical
    # session data. This ensures list_workers returns useful data after restart.
    if not is_recovery_attempted():
        logger.info("Attempting eager recovery from event log...")
        report = recover_registry(ctx.registry)
        if report is not None:
            logger.info(
                "Event log recovery complete: added=%d, skipped=%d, closed=%d",
                report.added,
                report.skipped,
                report.closed,
            )
            # Reconnect recovered sessions to live terminal panes.
            # This must run BEFORE pruning — promoted sessions move to _sessions
            # and won't be re-examined by the pruner.
            try:
                reconnect_report = await ctx.registry.reconnect_recovered_sessions(ctx.terminal_backend)
                if reconnect_report.reconnected or reconnect_report.closed:
                    logger.info(
                        "Reconnected recovered sessions: reconnected=%d closed=%d skipped=%d",
                        reconnect_report.reconnected,
                        reconnect_report.closed,
                        reconnect_report.skipped,
                    )
                if reconnect_report.errors:
                    for err in reconnect_report.errors:
                        logger.warning("Reconnect error: %s", err)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to reconnect recovered sessions: %s", exc)

            # Prune stale recovered sessions (terminal panes that no longer exist).
            try:
                prune_report = await ctx.registry.prune_stale_recovered_sessions(ctx.terminal_backend)
                if prune_report.pruned:
                    logger.info(
                        "Pruned stale recovered sessions: pruned=%d emitted_closed=%d",
                        prune_report.pruned,
                        prune_report.emitted_closed,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to prune stale recovered sessions: %s", exc)

            # Also prune managed sessions with dead panes (from prior runs).
            try:
                managed_pruned = await ctx.registry.prune_stale_managed_sessions(ctx.terminal_backend)
                if managed_pruned:
                    logger.info(
                        "Pruned stale managed sessions: %d removed (%s)",
                        len(managed_pruned),
                        ", ".join(managed_pruned),
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to prune stale managed sessions: %s", exc)
        else:
            logger.info("No event log data available for recovery")

    poller: WorkerPoller | None = None
    if enable_poller:
        poller = get_global_poller(ctx.registry)
        poller.start()

    try:
        yield ctx
    finally:
        # Keep the global poller running across per-session lifespans.
        # Cleanup: close any remaining sessions gracefully
        logger.info("Maniple MCP Server shutting down...")
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
        "Maniple Manager",
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
    log_path = configure_logging()
    if transport == "streamable-http":
        logger.info("Starting Maniple MCP Server (HTTP on port %s). Logs: %s", port, log_path)
        # Create server with configured port for HTTP mode
        server = create_mcp_server(host="127.0.0.1", port=port, enable_poller=True)
        server.run(transport="streamable-http")
    else:
        logger.info("Starting Maniple MCP Server (stdio). Logs: %s", log_path)
        mcp.run(transport="stdio")


def main():
    """CLI entry point with argument parsing."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Maniple MCP Server")
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
    # Config subcommands for reading/writing ~/.maniple/config.json.
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser(
        "config",
        help="Manage maniple configuration",
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

    events_parser = subparsers.add_parser(
        "events",
        help="Manage event log backups",
    )
    events_subparsers = events_parser.add_subparsers(dest="events_command")

    prune_parser = events_subparsers.add_parser(
        "prune",
        help="Prune rotated event log backups (events.*.jsonl)",
    )
    prune_parser.add_argument(
        "--keep-days",
        type=int,
        default=None,
        help="Delete backups older than this many days (by mtime).",
    )
    prune_parser.add_argument(
        "--max-total-size-mb",
        type=int,
        default=None,
        help="Cap total backup size by deleting oldest backups first.",
    )
    prune_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files (default: dry run).",
    )

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

    if args.command == "events":
        from maniple.events import prune_event_backups

        report = prune_event_backups(
            keep_days=args.keep_days,
            max_total_size_mb=args.max_total_size_mb,
            dry_run=not args.apply,
        )
        for path in report.deleted_paths:
            print(path)
        action = "Would delete" if not args.apply else "Deleted"
        print(
            f"{action} {report.deleted_count} backup(s). "
            f"Kept {report.kept_count} backup(s)."
        )
        return

    # Default behavior: run the MCP server.
    if args.http:
        run_server(transport="streamable-http", port=args.port)
    else:
        run_server(transport="stdio")


if __name__ == "__main__":
    main()
