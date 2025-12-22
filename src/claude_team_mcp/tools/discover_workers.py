"""
Discover workers tool.

Provides discover_workers for finding existing Claude Code sessions in iTerm2.
"""

import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from ..iterm_utils import read_screen_text
from ..session_state import (
    CLAUDE_PROJECTS_DIR,
    find_active_session,
    find_jsonl_by_iterm_id,
    get_project_dir,
    parse_session,
    unslugify_path,
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

        Scans all iTerm2 windows, tabs, and panes to find sessions that appear
        to be running Claude Code. Attempts to match each session to its JSONL
        file in ~/.claude/projects/ based on the project path visible on screen.

        Args:
            max_age: Only check JSONL files modified within this many seconds (default 3600)

        Returns:
            Dict with:
                - sessions: List of discovered sessions, each containing:
                    - iterm_session_id: iTerm2's internal session ID
                    - project_path: Detected project path (if found)
                    - claude_session_id: Matched JSONL session ID (if found)
                    - model: Detected model (Opus/Sonnet/Haiku if visible)
                    - last_assistant_preview: Preview of last assistant message (if JSONL found)
                    - already_managed: True if this session is already in our registry
                - count: Total number of Claude sessions found
                - unmanaged_count: Number not yet imported into registry
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

        # Scan all iTerm2 sessions
        for window in app.terminal_windows:
            for tab in window.tabs:
                for iterm_session in tab.sessions:
                    try:
                        screen_text = await read_screen_text(iterm_session)

                        # Detect if this is a Claude Code session by looking for indicators:
                        # - Model name (Opus, Sonnet, Haiku)
                        # - Prompt character (>)
                        # - Common Claude Code UI elements
                        is_claude = False
                        detected_model = None

                        for model in ["Opus", "Sonnet", "Haiku"]:
                            if model in screen_text:
                                is_claude = True
                                detected_model = model
                                break

                        # Also check for Claude-specific patterns
                        if not is_claude:
                            # Look for status line patterns: "ctx:", "tokens", "api:✓"
                            if "ctx:" in screen_text or "tokens" in screen_text:
                                is_claude = True

                        if not is_claude:
                            continue

                        # Try to extract project path from screen
                        # Look for "git:(" pattern which shows git branch, indicating project dir
                        # Or extract from visible path patterns
                        project_path = None
                        claude_session_id = None

                        # Parse screen lines for project info
                        lines = [l.strip() for l in screen_text.split("\n") if l.strip()]

                        # Look for git branch indicator which often shows project name
                        for line in lines:
                            # Pattern: "project-name git:(branch)" in status line
                            if "git:(" in line:
                                # Extract the part before "git:("
                                parts = line.split("git:(")[0].strip().split()
                                if parts:
                                    project_name = parts[-1]
                                    # Try to find this project in Claude's projects dir
                                    for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
                                        if proj_dir.is_dir() and project_name in proj_dir.name:
                                            # Use unslugify_path to handle hyphens in names
                                            # correctly (e.g., claude-iterm-controller)
                                            reconstructed = unslugify_path(proj_dir.name)
                                            if reconstructed:
                                                project_path = reconstructed
                                                break
                                break

                        # If we found a project path, try to find the active JSONL session
                        if project_path:
                            # Find most recently active session for this project
                            claude_session_id = find_active_session(
                                project_path, max_age_seconds=3600  # Within last hour
                            )

                        # Fallback: try to find JSONL by iTerm marker
                        # This works for sessions spawned by claude-team that have
                        # the iTerm-specific marker in their JSONL
                        internal_session_id = None
                        if not project_path:
                            match = find_jsonl_by_iterm_id(iterm_session.session_id, max_age_seconds=max_age)
                            if match:
                                project_path = match.project_path
                                claude_session_id = match.jsonl_path.stem
                                internal_session_id = match.internal_session_id

                        # Get last assistant message preview from JSONL if available
                        last_assistant_preview = None
                        if project_path and claude_session_id:
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
                            "internal_session_id": internal_session_id,  # Our session ID if recovered via marker
                            "model": detected_model,
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
