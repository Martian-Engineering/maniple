"""
Close workers tool.

Provides close_workers for gracefully terminating Claude Code worker sessions.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..iterm_utils import send_prompt, send_key, close_pane
from ..registry import SessionRegistry, SessionStatus
from ..worktree import WorktreeError, remove_worktree
from ..utils import error_response, HINTS

logger = logging.getLogger("claude-team-mcp")


async def _close_single_worker(
    session,
    session_id: str,
    registry: "SessionRegistry",
    force: bool = False,
) -> dict:
    """
    Close a single worker session.

    Internal helper for close_workers. Handles the actual close logic
    for one session.

    Args:
        session: The ManagedSession object
        session_id: ID of the session to close
        registry: The session registry
        force: If True, force close even if session is busy

    Returns:
        Dict with success status and worktree_cleaned flag
    """
    # Check if busy
    if session.status == SessionStatus.BUSY and not force:
        return {
            "success": False,
            "error": "Session is busy",
            "hint": HINTS["session_busy"],
            "worktree_cleaned": False,
        }

    try:
        # Send Ctrl+C to interrupt any running operation
        await send_key(session.iterm_session, "ctrl-c")
        # TODO(rabsef-bicrym): Programmatically time these actions
        await asyncio.sleep(1.0)

        # Send /exit to quit Claude
        await send_prompt(session.iterm_session, "/exit", submit=True)
        # TODO(rabsef-bicrym): Programmatically time these actions
        await asyncio.sleep(1.0)

        # Clean up worktree if exists (keeps branch alive for cherry-picking)
        worktree_cleaned = False
        if session.worktree_path and session.main_repo_path:
            try:
                remove_worktree(
                    repo_path=session.main_repo_path,
                    worktree_path=session.worktree_path,
                )
                worktree_cleaned = True
            except WorktreeError as e:
                # Log but don't fail the close
                logger.warning(f"Failed to clean up worktree for {session_id}: {e}")

        # Close the iTerm2 pane/window
        await close_pane(session.iterm_session, force=force)

        # Remove from registry
        registry.remove(session_id)

        return {
            "success": True,
            "worktree_cleaned": worktree_cleaned,
        }

    except Exception as e:
        logger.error(f"Failed to close session {session_id}: {e}")
        # Still try to remove from registry
        registry.remove(session_id)
        return {
            "success": True,
            "warning": f"Session removed but cleanup may be incomplete: {e}",
            "worktree_cleaned": False,
        }


def register_tools(mcp: FastMCP) -> None:
    """Register close_workers tool on the MCP server."""

    @mcp.tool()
    async def close_workers(
        ctx: Context[ServerSession, "AppContext"],
        session_ids: list[str],
        force: bool = False,
    ) -> dict:
        """
        Close one or more managed Claude Code sessions.

        Gracefully terminates the Claude sessions in parallel and closes
        their iTerm2 panes. All session_ids must exist in the registry.

        ⚠️ **NOTE: WORKTREE CLEANUP**
        Workers with worktrees commit to ephemeral branches. When closed:
        - The worktree directory is removed
        - The branch is KEPT for cherry-picking/merging

        **AFTER closing workers with worktrees:**
        1. Review commits on the worker's branch
        2. Merge or cherry-pick commits to a persistent branch
        3. Delete the branch when done: `git branch -D <branch-name>`

        Args:
            session_ids: List of session IDs to close (1 or more required).
                Accepts internal IDs, terminal IDs, or worker names.
            force: If True, force close even if sessions are busy

        Returns:
            Dict with:
                - session_ids: List of session IDs that were requested
                - results: Dict mapping session_id to individual result
                - success_count: Number of sessions closed successfully
                - failure_count: Number of sessions that failed to close
        """
        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        if not session_ids:
            return error_response(
                "No session_ids provided",
                hint="Provide at least one session_id to close",
            )

        # Validate all sessions exist first (fail fast)
        sessions_to_close = []
        missing_sessions = []

        for sid in session_ids:
            session = registry.resolve(sid)
            if not session:
                missing_sessions.append(sid)
            else:
                sessions_to_close.append((sid, session))

        # If any sessions are missing, fail the entire operation
        if missing_sessions:
            return error_response(
                f"Sessions not found: {', '.join(missing_sessions)}",
                hint=HINTS["session_not_found"],
                session_ids=session_ids,
                missing=missing_sessions,
            )

        # Close all sessions in parallel
        async def close_one(sid: str, session) -> tuple[str, dict]:
            result = await _close_single_worker(session, sid, registry, force)
            return (sid, result)

        tasks = [close_one(sid, session) for sid, session in sessions_to_close]
        parallel_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        results = {}
        for item in parallel_results:
            if isinstance(item, BaseException):
                # Shouldn't happen since _close_single_worker catches exceptions
                logger.error(f"Unexpected exception in close_workers: {item}")
                continue
            # Type narrowing: item is now tuple[str, dict]
            sid, result = item
            results[sid] = result

        success_count = sum(1 for r in results.values() if r.get("success", False))
        failure_count = len(results) - success_count

        return {
            "session_ids": session_ids,
            "results": results,
            "success_count": success_count,
            "failure_count": failure_count,
        }
