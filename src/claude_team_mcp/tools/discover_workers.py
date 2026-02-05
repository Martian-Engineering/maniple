"""
Discover workers tool.

Provides discover_workers for finding existing Claude Code and Codex sessions.
"""

import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..session_state import (
    find_codex_session_by_iterm_id,
    find_codex_session_by_tmux_id,
    find_jsonl_by_iterm_id,
    find_jsonl_by_tmux_id,
    get_project_dir,
    parse_codex_session,
    parse_session,
)
from ..utils import error_response, HINTS

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register discover_workers tool on the MCP server."""

    @mcp.tool()
    async def discover_workers(
        ctx: Context[ServerSession, "AppContext"],
        max_age: int | None = 3600,
    ) -> dict:
        """
        Discover existing Claude Code and Codex sessions running in the active terminal backend.

        For each terminal session, searches JSONL files in ~/.claude/projects/ and
        ~/.codex/sessions/ for matching terminal session markers. Sessions spawned
        by claude-team write their terminal IDs into the JSONL
        (e.g., <!claude-team-iterm:UUID!> or <!claude-team-tmux:%1!>), enabling
        reliable detection and recovery after MCP server restarts.
        For tmux, only panes in claude-team-managed sessions are scanned.

        Only JSONL files modified within max_age seconds are checked. If a session
        was started more than max_age seconds ago and hasn't had recent activity,
        it won't be discovered. Increase max_age to find older sessions.

        Args:
            max_age: Only check JSONL files modified within this many seconds.
                Default 3600 (1 hour). Use 86400 (24 hours) for older sessions.

        Returns:
            Dict with:
                - sessions: List of discovered sessions, each containing:
                    - backend_id: Terminal backend identifier
                    - iterm_session_id: iTerm2's internal session ID (iTerm backend)
                    - tmux_pane_id: tmux pane id (tmux backend)
                    - project_path: Detected project path
                    - claude_session_id: The JSONL session UUID (Claude only)
                    - codex_session_id: The JSONL session UUID (Codex only)
                    - internal_session_id: Our short session ID (e.g., "b48e2d5b")
                    - last_assistant_preview: Preview of last assistant message
                    - already_managed: True if already in our registry
                    - agent_type: "claude" or "codex"
                - count: Total number of sessions found
                - unmanaged_count: Number not yet in registry (available to adopt)
        """
        # Handle None values from MCP clients that send explicit null for omitted params
        max_age = max_age if max_age is not None else 3600

        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Ensure we have a fresh backend connection/state
        backend = await ensure_connection(app_ctx)
        backend_id = backend.backend_id

        if backend_id not in ("iterm", "tmux"):
            return error_response(
                "discover_workers is only supported with iTerm2 or tmux backend",
                hint=HINTS["terminal_backend_required"],
            )

        discovered = []

        managed_ids = {
            s.terminal_session.native_id
            for s in registry.list_all()
            if hasattr(s, 'terminal_session') and s.terminal_session.backend_id == backend_id
        }

        try:
            terminal_sessions = await backend.list_sessions()
        except Exception as e:
            logger.warning(f"Error listing sessions for backend {backend_id}: {e}")
            terminal_sessions = []

        for terminal_session in terminal_sessions:
            native_id = terminal_session.native_id
            try:
                if backend_id == "iterm":
                    # Look for this iTerm session ID in recent JSONL files
                    match = find_jsonl_by_iterm_id(
                        native_id,
                        max_age_seconds=max_age,
                    )

                    if match:
                        project_path = match.project_path
                        claude_session_id = match.jsonl_path.stem
                        internal_session_id = match.internal_session_id

                        # Get last assistant message preview from JSONL
                        last_assistant_preview = None
                        try:
                            jsonl_path = (
                                get_project_dir(project_path)
                                / f"{claude_session_id}.jsonl"
                            )
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
                            "backend_id": backend_id,
                            "iterm_session_id": native_id,
                            "project_path": project_path,
                            "claude_session_id": claude_session_id,
                            "internal_session_id": internal_session_id,
                            "last_assistant_preview": last_assistant_preview,
                            "already_managed": native_id in managed_ids,
                            "agent_type": "claude",
                        })
                        continue

                    # Fall back to Codex marker scan if no Claude match
                    codex_match = find_codex_session_by_iterm_id(
                        native_id,
                        max_age_seconds=max_age,
                    )

                    if not codex_match:
                        continue

                    project_path = codex_match.project_path
                    internal_session_id = codex_match.internal_session_id

                    # Get last assistant message preview from Codex JSONL
                    last_assistant_preview = None
                    try:
                        jsonl_path = codex_match.jsonl_path
                        if jsonl_path.exists():
                            state = parse_codex_session(jsonl_path)
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
                        "backend_id": backend_id,
                        "iterm_session_id": native_id,
                        "project_path": project_path,
                        "codex_session_id": codex_match.jsonl_path.stem,
                        "internal_session_id": internal_session_id,
                        "last_assistant_preview": last_assistant_preview,
                        "already_managed": native_id in managed_ids,
                        "agent_type": "codex",
                    })
                    continue

                # Tmux backend
                match = find_jsonl_by_tmux_id(
                    native_id,
                    max_age_seconds=max_age,
                )

                if not match:
                    # Fall back to Codex marker scan if no Claude match
                    codex_match = find_codex_session_by_tmux_id(
                        native_id,
                        max_age_seconds=max_age,
                    )

                    if not codex_match:
                        continue

                    project_path = codex_match.project_path
                    internal_session_id = codex_match.internal_session_id

                    # Get last assistant message preview from Codex JSONL
                    last_assistant_preview = None
                    try:
                        jsonl_path = codex_match.jsonl_path
                        if jsonl_path.exists():
                            state = parse_codex_session(jsonl_path)
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
                        "backend_id": backend_id,
                        "tmux_pane_id": native_id,
                        "project_path": project_path,
                        "codex_session_id": codex_match.jsonl_path.stem,
                        "internal_session_id": internal_session_id,
                        "last_assistant_preview": last_assistant_preview,
                        "already_managed": native_id in managed_ids,
                        "agent_type": "codex",
                    })
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
                    "backend_id": backend_id,
                    "tmux_pane_id": native_id,
                    "project_path": project_path,
                    "claude_session_id": claude_session_id,
                    "internal_session_id": internal_session_id,
                    "last_assistant_preview": last_assistant_preview,
                    "already_managed": native_id in managed_ids,
                    "agent_type": "claude",
                })

            except Exception as e:
                logger.warning(f"Error scanning session {native_id}: {e}")
                continue

        unmanaged = [s for s in discovered if not s["already_managed"]]

        return {
            "sessions": discovered,
            "count": len(discovered),
            "unmanaged_count": len(unmanaged),
        }
