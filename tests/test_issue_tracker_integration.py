"""Integration tests for issue tracker abstraction with worker prompts."""

import pytest

from claude_team_mcp.worker_prompt import generate_worker_prompt
from claude_team_mcp.issue_tracker import (
    BEADS_BACKEND,
    PEBBLES_BACKEND,
    detect_issue_tracker,
)


class TestTrackerDetectionWithWorkerPrompts:
    """Test that worker prompts use the correct tracker backend."""

    def test_pebbles_project_generates_pb_commands(self, tmp_path):
        """Pebbles project should generate pb commands in worker prompt."""
        # Setup: Create project with .pebbles marker
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        # Verify detection
        backend = detect_issue_tracker(str(project_path))
        assert backend == PEBBLES_BACKEND

        # Generate worker prompt with issue ID
        issue_id = "cic-123"
        prompt = generate_worker_prompt(
            "test-session",
            "TestWorker",
            bead=issue_id,
            project_path=str(project_path),
        )

        # Assert: Prompt should contain Pebbles commands
        assert "pb update cic-123 -status in_progress" in prompt
        assert "pb close cic-123" in prompt
        assert "pb show cic-123" in prompt
        assert "Use the pebbles CLI (`pb`)" in prompt

        # Assert: Should NOT contain Beads commands
        assert "bd --no-db" not in prompt
        assert "beads CLI" not in prompt.lower()

    def test_beads_project_generates_bd_commands(self, tmp_path):
        """Beads project should generate bd --no-db commands in worker prompt."""
        # Setup: Create project with .beads marker
        project_path = tmp_path / "beads-repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()

        # Verify detection
        backend = detect_issue_tracker(str(project_path))
        assert backend == BEADS_BACKEND

        # Generate worker prompt with issue ID
        issue_id = "cic-456"
        prompt = generate_worker_prompt(
            "test-session",
            "TestWorker",
            bead=issue_id,
            project_path=str(project_path),
        )

        # Assert: Prompt should contain Beads commands
        assert "bd --no-db update cic-456 --status in_progress" in prompt
        assert "bd --no-db close cic-456" in prompt
        assert "bd --no-db show cic-456" in prompt
        assert "Use the beads CLI (`bd`)" in prompt

        # Assert: Should NOT contain Pebbles commands
        assert "pb update" not in prompt
        assert "pb close" not in prompt
        assert "pebbles CLI" not in prompt.lower()

    def test_both_markers_defaults_to_pebbles(self, tmp_path, caplog):
        """Project with both markers should default to Pebbles with warning."""
        # Setup: Create project with both markers
        project_path = tmp_path / "both-markers-repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()
        (project_path / ".pebbles").mkdir()

        # Verify detection
        backend = detect_issue_tracker(str(project_path))
        assert backend == PEBBLES_BACKEND
        assert "defaulting to pebbles" in caplog.text

        # Generate worker prompt
        issue_id = "cic-789"
        prompt = generate_worker_prompt(
            "test-session",
            "TestWorker",
            bead=issue_id,
            project_path=str(project_path),
        )

        # Assert: Should use Pebbles commands
        assert "pb update cic-789" in prompt
        assert "pb close cic-789" in prompt
        assert "Use the pebbles CLI (`pb`)" in prompt

        # Assert: Should NOT use Beads commands
        assert "bd --no-db" not in prompt

    def test_no_tracker_shows_generic_instructions(self, tmp_path):
        """Project with no tracker should show generic instructions."""
        # Setup: Create project with no tracker markers
        project_path = tmp_path / "no-tracker-repo"
        project_path.mkdir()

        # Verify detection
        backend = detect_issue_tracker(str(project_path))
        assert backend is None

        # Generate worker prompt with issue ID
        issue_id = "cic-abc"
        prompt = generate_worker_prompt(
            "test-session",
            "TestWorker",
            bead=issue_id,
            project_path=str(project_path),
        )

        # Assert: Should have generic instructions
        assert "Mark in progress in the issue tracker" in prompt
        assert "Close the issue when done" in prompt
        assert "No issue tracker detected" in prompt
        assert "Supported trackers:" in prompt

        # Assert: Should NOT contain specific tracker commands
        assert "pb update" not in prompt
        assert "bd --no-db update" not in prompt
        assert "Use the pebbles CLI" not in prompt
        assert "Use the beads CLI" not in prompt

    def test_no_project_path_shows_generic_instructions(self):
        """Worker without project_path should show generic instructions."""
        # Generate worker prompt without project_path
        issue_id = "cic-xyz"
        prompt = generate_worker_prompt(
            "test-session",
            "TestWorker",
            bead=issue_id,
            project_path=None,
        )

        # Assert: Should have generic instructions
        assert "Mark in progress in the issue tracker" in prompt
        assert "Close the issue when done" in prompt
        assert "No issue tracker detected" in prompt

        # Assert: Should NOT contain specific tracker commands
        assert "pb update" not in prompt
        assert "bd --no-db update" not in prompt


class TestCommandTemplateFormatting:
    """Test that command templates are correctly formatted with parameters."""

    def test_pebbles_update_command_formatting(self, tmp_path):
        """Pebbles update command should use -status flag."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-test",
            project_path=str(project_path),
        )

        # Pebbles uses -status, not --status
        assert "pb update cic-test -status in_progress" in prompt
        assert "pb update cic-test --status" not in prompt

    def test_beads_update_command_formatting(self, tmp_path):
        """Beads update command should use --status flag."""
        project_path = tmp_path / "beads-repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-test",
            project_path=str(project_path),
        )

        # Beads uses --status
        assert "bd --no-db update cic-test --status in_progress" in prompt
        assert "bd --no-db update cic-test -status" not in prompt

    def test_pebbles_show_command_in_assignment(self, tmp_path):
        """Pebbles show command should appear in assignment section."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-show-test",
            project_path=str(project_path),
        )

        # Should mention pb show in assignment
        assert "pb show cic-show-test" in prompt
        assert "for details" in prompt

    def test_beads_show_command_in_assignment(self, tmp_path):
        """Beads show command should appear in assignment section."""
        project_path = tmp_path / "beads-repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-show-test",
            project_path=str(project_path),
        )

        # Should mention bd show in assignment
        assert "bd --no-db show cic-show-test" in prompt
        assert "for details" in prompt


class TestCodexAgentTrackerIntegration:
    """Test tracker abstraction works for Codex agents."""

    def test_codex_pebbles_project_uses_pb_commands(self, tmp_path):
        """Codex worker in Pebbles project should use pb commands."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "CodexWorker",
            agent_type="codex",
            bead="cic-123",
            project_path=str(project_path),
        )

        # Should use Pebbles commands
        assert "pb update cic-123 -status in_progress" in prompt
        assert "pb close cic-123" in prompt
        assert "Use the pebbles CLI (`pb`)" in prompt

        # Should NOT use Beads commands
        assert "bd --no-db" not in prompt

    def test_codex_beads_project_uses_bd_commands(self, tmp_path):
        """Codex worker in Beads project should use bd commands."""
        project_path = tmp_path / "beads-repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "CodexWorker",
            agent_type="codex",
            bead="cic-456",
            project_path=str(project_path),
        )

        # Should use Beads commands
        assert "bd --no-db update cic-456 --status in_progress" in prompt
        assert "bd --no-db close cic-456" in prompt
        assert "Use the beads CLI (`bd`)" in prompt

        # Should NOT use Pebbles commands
        assert "pb update" not in prompt


class TestTrackerWorkflowSteps:
    """Test that tracker workflow steps are correctly numbered and ordered."""

    def test_workflow_numbered_as_step_4(self, tmp_path):
        """Tracker workflow should be step 4 in the prompt."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-123",
            project_path=str(project_path),
        )

        # Should be numbered as step 4
        assert "4. **Issue tracker workflow.**" in prompt

    def test_commit_step_appears_with_worktree_no_issue(self, tmp_path):
        """Commit step should appear as step 4 when worktree but no issue."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            use_worktree=True,
            project_path=str(project_path),
        )

        # Should have commit step
        assert "4. **Commit when done.**" in prompt
        assert "cherry-pick" in prompt

    def test_no_extra_steps_without_issue_or_worktree(self, tmp_path):
        """No extra numbered steps when no issue or worktree."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            project_path=str(project_path),
        )

        # Should not have step 4
        assert "4." not in prompt

    def test_workflow_includes_all_steps_in_order(self, tmp_path):
        """Tracker workflow should include all steps in correct order."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-123",
            project_path=str(project_path),
        )

        # Find the workflow section
        workflow_start = prompt.index("4. **Issue tracker workflow.**")
        workflow_section = prompt[workflow_start:workflow_start + 500]

        # Check order of steps
        mark_in_progress_pos = workflow_section.index("Mark in progress:")
        implement_pos = workflow_section.index("Implement the changes")
        close_pos = workflow_section.index("Close issue:")
        commit_pos = workflow_section.index("Commit with issue reference:")

        # Verify order
        assert mark_in_progress_pos < implement_pos < close_pos < commit_pos


class TestTrackerCommitInstructions:
    """Test tracker-specific commit message formatting."""

    def test_pebbles_commit_includes_issue_id(self, tmp_path):
        """Pebbles workflow should include issue ID in commit message."""
        project_path = tmp_path / "pebbles-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-commit",
            project_path=str(project_path),
        )

        # Should instruct to include issue ID
        assert 'git commit -m "cic-commit:' in prompt

    def test_beads_commit_includes_issue_id(self, tmp_path):
        """Beads workflow should include issue ID in commit message."""
        project_path = tmp_path / "beads-repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()

        prompt = generate_worker_prompt(
            "test",
            "Worker",
            bead="cic-commit",
            project_path=str(project_path),
        )

        # Should instruct to include issue ID
        assert 'git commit -m "cic-commit:' in prompt
