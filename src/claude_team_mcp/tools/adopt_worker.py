"""
Adopt worker tool.

Provides adopt_worker for importing existing terminal Claude Code and Codex sessions.
"""

import logging
import os
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..registry import SessionStatus
from ..session_state import (
    find_codex_session_by_iterm_id,
    find_codex_session_by_tmux_id,
    find_jsonl_by_iterm_id,
    find_jsonl_by_tmux_id,
)
from ..utils import error_response, HINTS

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register adopt_worker tool on the MCP server."""

    @mcp.tool()
    async def adopt_worker(
        ctx: Context[ServerSession, "AppContext"],
        iterm_session_id: str | None = None,
        tmux_pane_id: str | None = None,
        session_name: str | None = None,
        max_age: int = 3600,
    ) -> dict:
        """
        Adopt an existing terminal Claude Code or Codex session into the MCP registry.

        Takes a terminal session ID (from discover_workers) and registers it
        for management. Only works for sessions originally spawned by claude-team
        (which have markers in their JSONL for reliable correlation).

        Args:
            iterm_session_id: The iTerm2 session ID (from discover_workers)
            tmux_pane_id: The tmux pane ID (from discover_workers)
            session_name: Optional friendly name for the worker
            max_age: Only check JSONL files modified within this many seconds (default 3600)

        Returns:
            Dict with adopted worker info, or error if session not found
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Ensure we have a fresh backend connection/state
        backend = await ensure_connection(app_ctx)
        backend_id = backend.backend_id

        target_id = iterm_session_id if backend_id == "iterm" else tmux_pane_id
        if backend_id == "tmux" and not target_id:
            target_id = iterm_session_id
        if backend_id == "iterm" and not target_id:
            target_id = tmux_pane_id

        if not target_id:
            return error_response(
                "terminal session id is required",
                hint="Pass iterm_session_id or tmux_pane_id from discover_workers",
            )

        # Check if already managed
        for managed in registry.list_all():
            if (
                managed.terminal_session.backend_id == backend_id
                and managed.terminal_session.native_id == target_id
            ):
                return error_response(
                    f"Session already managed as '{managed.session_id}'",
                    hint="Use message_workers to communicate with the existing session",
                    existing_session=managed.to_dict(),
                )

        # Find the terminal session by ID
        target_session = None
        try:
            terminal_sessions = await backend.list_sessions()
        except Exception as e:
            logger.warning(f"Error listing sessions for backend {backend_id}: {e}")
            terminal_sessions = []

        for session in terminal_sessions:
            if session.native_id == target_id:
                target_session = session
                break

        if not target_session:
            return error_response(
                f"Terminal session not found: {target_id}",
                hint="Run discover_workers to scan for active Claude or Codex sessions",
            )

        # Use marker-based discovery to recover original session identity.
        # This only works for sessions we originally spawned (which have our markers).
        agent_type = "claude"
        match = None
        if backend_id == "iterm":
            match = find_jsonl_by_iterm_id(target_id, max_age_seconds=max_age)
            if not match:
                codex_match = find_codex_session_by_iterm_id(
                    target_id,
                    max_age_seconds=max_age,
                )
                if not codex_match:
                    return error_response(
                        "Session not found or not spawned by claude-team",
                        hint="adopt_worker only works for sessions originally spawned by claude-team. "
                        "External sessions cannot be reliably correlated to their JSONL files.",
                        iterm_session_id=target_id,
                    )
                match = codex_match
                agent_type = "codex"
        elif backend_id == "tmux":
            match = find_jsonl_by_tmux_id(target_id, max_age_seconds=max_age)
            if not match:
                codex_match = find_codex_session_by_tmux_id(
                    target_id,
                    max_age_seconds=max_age,
                )
                if not codex_match:
                    return error_response(
                        "Session not found or not spawned by claude-team",
                        hint="adopt_worker only works for sessions originally spawned by claude-team. "
                        "External sessions cannot be reliably correlated to their JSONL files.",
                        tmux_pane_id=target_id,
                    )
                match = codex_match
                agent_type = "codex"
        else:
            return error_response(
                "adopt_worker is only supported with iTerm2 or tmux backend",
                hint=HINTS["terminal_backend_required"],
            )

        logger.info(
            "Recovered session via terminal marker: "
            f"project={match.project_path}, internal_id={match.internal_session_id}, "
            f"agent_type={agent_type}"
        )

        # Validate project path still exists
        if not os.path.isdir(match.project_path):
            return error_response(
                f"Project path no longer exists: {match.project_path}",
                hint=HINTS["project_path_missing"],
            )

        # Register with recovered identity (no new marker needed)
        managed = registry.add(
            terminal_session=target_session,
            project_path=match.project_path,
            name=session_name,
            session_id=match.internal_session_id,  # Recover original ID
        )
        managed.agent_type = agent_type
        if agent_type == "claude":
            managed.claude_session_id = match.jsonl_path.stem

        # Mark ready immediately (no discovery needed, we already have it)
        registry.update_status(managed.session_id, SessionStatus.READY)

        return {
            "success": True,
            "message": f"Session recovered as '{managed.session_id}'",
            "session": managed.to_dict(),
        }
