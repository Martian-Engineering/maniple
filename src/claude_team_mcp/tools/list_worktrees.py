"""
List worktrees tool.

Provides list_worktrees for managing claude-team created git worktrees.
"""

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..worktree import (
    list_local_worktrees,
    LOCAL_WORKTREE_DIR,
)
from ..utils import error_response, HINTS

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP) -> None:
    """Register list_worktrees tool on the MCP server."""

    @mcp.tool()
    async def list_worktrees(
        ctx: Context[ServerSession, "AppContext"],
        repo_path: str,
        remove_orphans: bool = False,
    ) -> dict:
        """
        List worktrees in a repository's .worktrees/ directory.

        Shows all worktrees created by claude-team for the specified repository,
        including which are orphaned (directory exists but not registered with git).

        Args:
            repo_path: Path to the repository to list worktrees for
            remove_orphans: If True, remove worktrees that are not registered with git

        Returns:
            Dict with:
                - repo_path: The repository path
                - worktrees_dir: Path to .worktrees/ directory
                - worktrees: List of worktree info dicts containing:
                    - path: Full path to worktree
                    - name: Directory name (e.g., "cic-abc-fix-bug")
                    - branch: Git branch (if registered)
                    - commit: Current commit (if registered)
                    - registered: True if git knows about this worktree
                    - removed: True if orphan was removed (when remove_orphans=True)
                - total: Total number of worktrees
                - orphan_count: Number of orphaned worktrees
                - removed_count: Number of orphans removed (when remove_orphans=True)
        """
        resolved_path = Path(repo_path).resolve()
        if not resolved_path.exists():
            return error_response(
                f"Repository path does not exist: {repo_path}",
                hint=HINTS["project_path_missing"],
            )

        worktrees_dir = resolved_path / LOCAL_WORKTREE_DIR
        worktrees = list_local_worktrees(resolved_path)

        result_worktrees = []
        orphan_count = 0
        removed_count = 0

        for wt in worktrees:
            wt_info = {
                "path": str(wt["path"]),
                "name": wt["name"],
                "branch": wt["branch"],
                "commit": wt["commit"],
                "registered": wt["registered"],
                "removed": False,
            }

            if not wt["registered"]:
                orphan_count += 1
                if remove_orphans:
                    try:
                        # Remove the orphaned directory
                        shutil.rmtree(wt["path"])
                        wt_info["removed"] = True
                        removed_count += 1
                        logger.info(f"Removed orphaned worktree: {wt['path']}")
                    except Exception as e:
                        logger.warning(f"Failed to remove orphaned worktree {wt['path']}: {e}")

            result_worktrees.append(wt_info)

        return {
            "repo_path": str(resolved_path),
            "worktrees_dir": str(worktrees_dir),
            "worktrees": result_worktrees,
            "total": len(worktrees),
            "orphan_count": orphan_count,
            "removed_count": removed_count,
        }
