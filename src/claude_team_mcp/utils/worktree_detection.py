"""
Git worktree detection utilities.

Detects if a project path is a git worktree and locates the main repo's
issue tracker marker directory for proper issue tracking.
"""

import logging
import os
import subprocess

from claude_team_mcp.issue_tracker import (
    BEADS_BACKEND,
    PEBBLES_BACKEND,
    detect_issue_tracker,
)

logger = logging.getLogger("claude-team-mcp")


def get_worktree_tracker_dir(project_path: str) -> tuple[str, str] | None:
    """
    Detect if project_path is a git worktree and return tracker env var + dir.

    Git worktrees have .git as a file (not a directory) pointing to the main repo.
    The `git rev-parse --git-common-dir` command returns the path to the shared
    .git directory, which we can use to find the main repo.

    Args:
        project_path: Absolute path to the project directory

    Returns:
        (env_var, tracker_dir) if:
        - project_path is a git worktree
        - The main repo has a tracker marker (.beads or .pebbles)
        Otherwise returns None.
    """
    try:
        # Run git rev-parse --git-common-dir to get the shared .git directory
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            # Not a git repo or git command failed
            return None

        git_common_dir = result.stdout.strip()

        # If the result is just ".git", this is the main repo (not a worktree).
        if git_common_dir == ".git":
            return None

        # git_common_dir is the path to the shared .git directory
        # The main repo is the parent of .git
        # Handle both absolute and relative paths
        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.join(project_path, git_common_dir)

        git_common_dir = os.path.normpath(git_common_dir)

        # Main repo is the parent directory of .git.
        main_repo = os.path.dirname(git_common_dir)

        # Identify which tracker is present in the main repo.
        tracker_backend = detect_issue_tracker(main_repo)
        if tracker_backend is None:
            return None

        # Map the detected tracker to its env var and marker directory.
        if tracker_backend is BEADS_BACKEND:
            env_var = "BEADS_DIR"
        elif tracker_backend is PEBBLES_BACKEND:
            env_var = "PEBBLES_DIR"
        else:
            logger.warning(
                "Unknown issue tracker backend %s for %s",
                tracker_backend.name,
                main_repo,
            )
            return None

        tracker_dir = os.path.join(main_repo, tracker_backend.marker_dir)
        logger.info(
            "Detected git worktree. Setting %s=%s for project %s",
            env_var,
            tracker_dir,
            project_path,
        )
        return env_var, tracker_dir

    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout checking git worktree status for {project_path}")
        return None
    except Exception as e:
        logger.warning(f"Error checking git worktree status for {project_path}: {e}")
        return None
