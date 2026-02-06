"""
List workers tool.

Provides list_workers for viewing all managed Claude Code sessions.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..registry import SessionStatus
from ..utils import error_response

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP) -> None:
    """Register list_workers tool on the MCP server."""

    @mcp.tool()
    async def list_workers(
        ctx: Context[ServerSession, "AppContext"],
        status_filter: str | None = None,
        project_filter: str | None = None,
    ) -> dict:
        """
        List all managed Claude Code sessions.

        Returns information about each session including its ID, name,
        project path, and current status. Results are sorted by creation time.

        Args:
            status_filter: Optional filter by status - "ready", "busy", "spawning", "closed"
            project_filter: Optional filter by project path (full path, basename, or partial match)

        Returns:
            Dict with:
                - workers: List of session info dicts
                - count: Number of workers returned
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Lazy fallback: if registry is empty and recovery hasn't been attempted,
        # try to recover from the event log. This handles edge cases where startup
        # recovery may have failed or wasn't triggered.
        from ..server import is_recovery_attempted, recover_registry

        if not is_recovery_attempted() and len(registry.list_all()) == 0:
            logger.info("Registry empty on first list_workers call, attempting lazy recovery...")
            report = recover_registry(registry)
            if report is not None:
                logger.info(
                    "Lazy recovery complete: added=%d, skipped=%d, closed=%d",
                    report.added,
                    report.skipped,
                    report.closed,
                )

        # Get sessions, optionally filtered by status
        if status_filter:
            try:
                status = SessionStatus(status_filter)
                sessions = registry.list_by_status(status)
            except ValueError:
                valid_statuses = [s.value for s in SessionStatus]
                return error_response(
                    f"Invalid status filter: {status_filter}",
                    hint=f"Valid statuses are: {', '.join(valid_statuses)}",
                )
        else:
            sessions = registry.list_all()

        # Filter by project path or main repo path
        if project_filter:
            normalized_filter = project_filter.strip()
            if normalized_filter:
                filtered_sessions = []
                for session in sessions:
                    candidates = [session.project_path]
                    if session.main_repo_path is not None:
                        candidates.append(str(session.main_repo_path))
                    matches = False
                    for candidate in candidates:
                        if not candidate:
                            continue
                        if candidate == normalized_filter:
                            matches = True
                            break
                        if Path(candidate).name == normalized_filter:
                            matches = True
                            break
                        if normalized_filter in candidate:
                            matches = True
                            break
                    if matches:
                        filtered_sessions.append(session)
                sessions = filtered_sessions

        # Sort by created_at (normalize to UTC-aware for mixed live/recovered)
        from datetime import timezone as _tz

        def _sort_key(s):
            dt = s.created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            return dt

        sessions = sorted(sessions, key=_sort_key)

        # Convert to dicts and add message count + idle status
        workers = []
        for session in sessions:
            info = session.to_dict()
            # Try to get conversation stats (only available on live ManagedSessions)
            if hasattr(session, "get_conversation_state"):
                state = session.get_conversation_state()
                if state:
                    info["message_count"] = state.message_count
            # Check idle using stop hook detection
            info["is_idle"] = session.is_idle()
            workers.append(info)

        return {
            "workers": workers,
            "count": len(workers),
        }
