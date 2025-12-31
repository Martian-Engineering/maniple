"""
Adopt worker tool.

Provides adopt_worker for importing existing iTerm2 Claude Code sessions.
"""

import logging
import os
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..registry import SessionStatus
from ..session_state import find_jsonl_by_iterm_id
from ..utils import error_response, HINTS

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register adopt_worker tool on the MCP server."""

    @mcp.tool()
    async def adopt_worker(
        ctx: Context[ServerSession, "AppContext"],
        iterm_session_id: str,
        session_name: str | None = None,
        max_age: int = 3600,
    ) -> dict:
        """
        Adopt an existing iTerm2 Claude Code session into the MCP registry.

        Takes an iTerm2 session ID (from discover_workers) and registers it
        for management. Only works for sessions originally spawned by claude-team
        (which have markers in their JSONL for reliable correlation).

        Args:
            iterm_session_id: The iTerm2 session ID (from discover_workers)
            session_name: Optional friendly name for the worker
            max_age: Only check JSONL files modified within this many seconds (default 3600)

        Returns:
            Dict with adopted worker info, or error if session not found
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Ensure we have a fresh connection (websocket can go stale)
        _, app = await ensure_connection(app_ctx)

        # Check if already managed
        for managed in registry.list_all():
            if managed.iterm_session.session_id == iterm_session_id:
                return error_response(
                    f"Session already managed as '{managed.session_id}'",
                    hint="Use message_workers to communicate with the existing session",
                    existing_session=managed.to_dict(),
                )

        # Find the iTerm2 session by ID
        target_session = None
        for window in app.terminal_windows:
            for tab in window.tabs:
                for iterm_session in tab.sessions:
                    if iterm_session.session_id == iterm_session_id:
                        target_session = iterm_session
                        break
                if target_session:
                    break
            if target_session:
                break

        if not target_session:
            return error_response(
                f"iTerm2 session not found: {iterm_session_id}",
                hint="Run discover_workers to scan for active Claude sessions in iTerm2",
            )

        # Use marker-based discovery to recover original session identity
        # This only works for sessions we originally spawned (which have our markers)
        match = find_jsonl_by_iterm_id(iterm_session_id, max_age_seconds=max_age)
        if not match:
            return error_response(
                "Session not found or not spawned by claude-team",
                hint="adopt_worker only works for sessions originally spawned by claude-team. "
                "External sessions cannot be reliably correlated to their JSONL files.",
                iterm_session_id=iterm_session_id,
            )

        logger.info(
            f"Recovered session via iTerm marker: "
            f"project={match.project_path}, internal_id={match.internal_session_id}"
        )

        # Validate project path still exists
        if not os.path.isdir(match.project_path):
            return error_response(
                f"Project path no longer exists: {match.project_path}",
                hint=HINTS["project_path_missing"],
            )

        # Register with recovered identity (no new marker needed)
        managed = registry.add(
            iterm_session=target_session,
            project_path=match.project_path,
            name=session_name,
            session_id=match.internal_session_id,  # Recover original ID
        )
        managed.claude_session_id = match.jsonl_path.stem

        # Mark ready immediately (no discovery needed, we already have it)
        registry.update_status(managed.session_id, SessionStatus.READY)

        return {
            "success": True,
            "message": f"Session recovered as '{managed.session_id}'",
            "session": managed.to_dict(),
        }
