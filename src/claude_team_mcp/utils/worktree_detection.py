"""
Git worktree detection utilities.

Detects if a project path is a git worktree and locates the main repo's
beads directory for proper issue tracking.
"""

import logging
import os
import subprocess

logger = logging.getLogger("claude-team-mcp")


def get_worktree_beads_dir(project_path: str) -> str | None:
    """
    Detect if project_path is a git worktree and return the main repo's .beads dir.

    Git worktrees have .git as a file (not a directory) pointing to the main repo.
    The `git rev-parse --git-common-dir` command returns the path to the shared
    .git directory, which we can use to find the main repo.

    Args:
        project_path: Absolute path to the project directory

    Returns:
        Path to the main repo's .beads directory if:
        - project_path is a git worktree
        - The main repo has a .beads directory
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

        # If the result is just ".git", this is the main repo (not a worktree)
        if git_common_dir == ".git":
            return None

        # git_common_dir is the path to the shared .git directory
        # The main repo is the parent of .git
        # Handle both absolute and relative paths
        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.join(project_path, git_common_dir)

        git_common_dir = os.path.normpath(git_common_dir)

        # Main repo is the parent directory of .git
        main_repo = os.path.dirname(git_common_dir)

        # Check if the main repo has a .beads directory
        beads_dir = os.path.join(main_repo, ".beads")
        if os.path.isdir(beads_dir):
            logger.info(
                f"Detected git worktree. Setting BEADS_DIR={beads_dir} "
                f"for project {project_path}"
            )
            return beads_dir

        return None

    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout checking git worktree status for {project_path}")
        return None
    except Exception as e:
        logger.warning(f"Error checking git worktree status for {project_path}: {e}")
        return None
