"""
Discover workers tool.

Provides discover_workers for finding existing Claude Code sessions in iTerm2.
"""

import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..session_state import (
    find_jsonl_by_iterm_id,
    get_project_dir,
    parse_session,
)

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register discover_workers tool on the MCP server."""

    @mcp.tool()
    async def discover_workers(
        ctx: Context[ServerSession, "AppContext"],
        max_age: int = 3600,
    ) -> dict:
        """
        Discover existing Claude Code sessions running in iTerm2.

        For each iTerm2 pane, searches JSONL files in ~/.claude/projects/ for a
        matching iTerm session ID marker. Sessions spawned by claude-team write
        their iTerm session ID into the JSONL (e.g., <!claude-team-iterm:UUID!>),
        enabling reliable detection and recovery after MCP server restarts.

        Only JSONL files modified within max_age seconds are checked. If a session
        was started more than max_age seconds ago and hasn't had recent activity,
        it won't be discovered. Increase max_age to find older sessions.

        Args:
            max_age: Only check JSONL files modified within this many seconds.
                Default 3600 (1 hour). Use 86400 (24 hours) for older sessions.

        Returns:
            Dict with:
                - sessions: List of discovered sessions, each containing:
                    - iterm_session_id: iTerm2's internal session ID
                    - project_path: Detected project path
                    - claude_session_id: The JSONL session UUID
                    - internal_session_id: Our short session ID (e.g., "b48e2d5b")
                    - last_assistant_preview: Preview of last assistant message
                    - already_managed: True if already in our registry
                - count: Total number of Claude sessions found
                - unmanaged_count: Number not yet in registry (available to adopt)
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Ensure we have a fresh connection (websocket can go stale)
        _, app = await ensure_connection(app_ctx)

        discovered = []

        # Get all managed iTerm session IDs so we can flag already-managed ones
        managed_iterm_ids = {
            s.iterm_session.session_id for s in registry.list_all()
        }

        # Scan all iTerm2 panes and check if their session ID appears in any JSONL
        for window in app.terminal_windows:
            for tab in window.tabs:
                for iterm_session in tab.sessions:
                    try:
                        # Look for this iTerm session ID in recent JSONL files
                        # Claude-team spawned sessions write their iTerm ID as a marker
                        match = find_jsonl_by_iterm_id(
                            iterm_session.session_id,
                            max_age_seconds=max_age
                        )

                        if not match:
                            # Not a Claude session we know about
                            continue

                        project_path = match.project_path
                        claude_session_id = match.jsonl_path.stem
                        internal_session_id = match.internal_session_id

                        # Get last assistant message preview from JSONL
                        last_assistant_preview = None
                        try:
                            jsonl_path = get_project_dir(project_path) / f"{claude_session_id}.jsonl"
                            if jsonl_path.exists():
                                state = parse_session(jsonl_path)
                                if state.last_assistant_message:
                                    content = state.last_assistant_message.content
                                    last_assistant_preview = (
                                        content[:200] + "..."
                                        if len(content) > 200
                                        else content
                                    )
                        except Exception as e:
                            logger.debug(f"Could not get conversation preview: {e}")

                        discovered.append({
                            "iterm_session_id": iterm_session.session_id,
                            "project_path": project_path,
                            "claude_session_id": claude_session_id,
                            "internal_session_id": internal_session_id,
                            "last_assistant_preview": last_assistant_preview,
                            "already_managed": iterm_session.session_id in managed_iterm_ids,
                        })

                    except Exception as e:
                        logger.warning(f"Error scanning session {iterm_session.session_id}: {e}")
                        continue

        unmanaged = [s for s in discovered if not s["already_managed"]]

        return {
            "sessions": discovered,
            "count": len(discovered),
            "unmanaged_count": len(unmanaged),
        }
