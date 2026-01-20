"""
Tests for worktree detection utilities.
"""

import subprocess
from unittest.mock import patch

from claude_team_mcp.utils.worktree_detection import get_worktree_tracker_dir


class TestGetWorktreeTrackerDir:
    """Tests for get_worktree_tracker_dir."""

    def test_returns_none_for_main_repo(self, tmp_path):
        """Main repo (not a worktree) should return None."""
        # Create a repo path without a worktree.
        project_path = tmp_path / "repo"
        project_path.mkdir()

        # Simulate git rev-parse returning ".git" (main repo).
        result = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--git-common-dir"],
            returncode=0,
            stdout=".git\n",
            stderr="",
        )

        # Patch subprocess.run to use the simulated git output.
        with patch(
            "claude_team_mcp.utils.worktree_detection.subprocess.run",
            return_value=result,
        ):
            assert get_worktree_tracker_dir(str(project_path)) is None

    def test_returns_beads_dir_for_worktree(self, tmp_path):
        """Worktree with beads marker should return BEADS_DIR info."""
        # Set up a main repo with .beads and a separate worktree directory.
        main_repo = tmp_path / "main-repo"
        worktree = tmp_path / "worktree"
        main_repo.mkdir()
        worktree.mkdir()
        (main_repo / ".beads").mkdir()
        (main_repo / ".git").mkdir()

        # Simulate git rev-parse pointing to the main repo .git directory.
        result = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--git-common-dir"],
            returncode=0,
            stdout=f"{main_repo / '.git'}\n",
            stderr="",
        )

        # Patch subprocess.run so the worktree detection uses the fake output.
        with patch(
            "claude_team_mcp.utils.worktree_detection.subprocess.run",
            return_value=result,
        ):
            assert get_worktree_tracker_dir(str(worktree)) == (
                "BEADS_DIR",
                str(main_repo / ".beads"),
            )

    def test_returns_pebbles_dir_for_worktree(self, tmp_path):
        """Worktree with pebbles marker should return PEBBLES_DIR info."""
        # Set up a main repo with .pebbles and a separate worktree directory.
        main_repo = tmp_path / "main-repo"
        worktree = tmp_path / "worktree"
        main_repo.mkdir()
        worktree.mkdir()
        (main_repo / ".pebbles").mkdir()
        (main_repo / ".git").mkdir()

        # Simulate git rev-parse pointing to the main repo .git directory.
        result = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--git-common-dir"],
            returncode=0,
            stdout=f"{main_repo / '.git'}\n",
            stderr="",
        )

        # Patch subprocess.run so the worktree detection uses the fake output.
        with patch(
            "claude_team_mcp.utils.worktree_detection.subprocess.run",
            return_value=result,
        ):
            assert get_worktree_tracker_dir(str(worktree)) == (
                "PEBBLES_DIR",
                str(main_repo / ".pebbles"),
            )

    def test_prefers_pebbles_when_both_markers_present(self, tmp_path):
        """Worktree should return pebbles env var when both markers exist."""
        # Set up a main repo with both markers and a separate worktree.
        main_repo = tmp_path / "main-repo"
        worktree = tmp_path / "worktree"
        main_repo.mkdir()
        worktree.mkdir()
        (main_repo / ".beads").mkdir()
        (main_repo / ".pebbles").mkdir()
        (main_repo / ".git").mkdir()

        # Simulate git rev-parse pointing to the main repo .git directory.
        result = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--git-common-dir"],
            returncode=0,
            stdout=f"{main_repo / '.git'}\n",
            stderr="",
        )

        # Patch subprocess.run so the worktree detection uses the fake output.
        with patch(
            "claude_team_mcp.utils.worktree_detection.subprocess.run",
            return_value=result,
        ):
            assert get_worktree_tracker_dir(str(worktree)) == (
                "PEBBLES_DIR",
                str(main_repo / ".pebbles"),
            )
