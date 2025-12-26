"""Tests for the worker_prompt module."""

import pytest

from claude_team_mcp.worker_prompt import (
    generate_worker_prompt,
    get_coordinator_guidance,
)


class TestGenerateWorkerPrompt:
    """Tests for generate_worker_prompt function."""

    def test_includes_worker_name(self):
        """Prompt should address the worker by name."""
        prompt = generate_worker_prompt("worker-1", "Ringo")
        assert "Ringo" in prompt

    def test_includes_do_work_fully_rule(self):
        """Prompt should contain the 'do work fully' instruction."""
        prompt = generate_worker_prompt("test-session", "George")
        assert "Do the work fully" in prompt

    def test_prompt_is_non_empty_string(self):
        """Prompt should be a non-empty string."""
        prompt = generate_worker_prompt("test", "Worker")
        assert isinstance(prompt, str)
        assert len(prompt) > 100  # Should be substantial


class TestAssignmentCases:
    """Tests for the 4 assignment cases in worker prompts."""

    def test_case1_bead_only(self):
        """With bead only, should show assignment and beads workflow."""
        prompt = generate_worker_prompt("test", "Worker", bead="cic-123")
        assert "Your assignment is `cic-123`" in prompt
        assert "bd show cic-123" in prompt
        assert "Beads workflow" in prompt
        assert "bd --no-db update cic-123" in prompt
        assert "bd --no-db close cic-123" in prompt
        assert "Get to work!" in prompt

    def test_case2_bead_and_custom_prompt(self):
        """With bead and custom prompt, should show both."""
        prompt = generate_worker_prompt(
            "test", "Worker",
            bead="cic-456",
            custom_prompt="Focus on the edge cases"
        )
        assert "`cic-456`" in prompt
        assert "bd show cic-456" in prompt
        assert "Focus on the edge cases" in prompt
        assert "Beads workflow" in prompt
        assert "Get to work!" in prompt

    def test_case3_custom_prompt_only(self):
        """With custom prompt only, should show the task."""
        prompt = generate_worker_prompt(
            "test", "Worker",
            custom_prompt="Review the auth module for security issues"
        )
        assert "Review the auth module for security issues" in prompt
        assert "The coordinator assigned you the following task" in prompt
        assert "Get to work!" in prompt
        # Should not have beads workflow
        assert "Beads workflow" not in prompt

    def test_case4_no_bead_no_prompt(self):
        """With neither bead nor prompt, should say coordinator will message."""
        prompt = generate_worker_prompt("test", "Worker")
        assert "The coordinator will send your first task shortly" in prompt
        # Should not have assignment section
        assert "YOUR ASSIGNMENT" not in prompt
        assert "Beads workflow" not in prompt


class TestBeadsWorkflow:
    """Tests for beads workflow instructions."""

    def test_beads_workflow_uses_no_db_flag(self):
        """Beads commands should use --no-db flag."""
        prompt = generate_worker_prompt("test", "Worker", bead="cic-abc")
        assert "bd --no-db update" in prompt
        assert "bd --no-db close" in prompt

    def test_beads_workflow_includes_commit_instruction(self):
        """Beads workflow should include commit with issue reference."""
        prompt = generate_worker_prompt("test", "Worker", bead="cic-abc")
        assert 'git commit -m "cic-abc:' in prompt


class TestGetCoordinatorGuidance:
    """Tests for get_coordinator_guidance function."""

    def test_returns_non_empty_string(self):
        """Should return a non-empty string."""
        guidance = get_coordinator_guidance([{"name": "Groucho", "bead": "cic-123"}])
        assert isinstance(guidance, str)
        assert len(guidance) > 0

    def test_contains_team_dispatched_header(self):
        """Guidance should have team dispatched header."""
        guidance = get_coordinator_guidance([{"name": "Groucho", "bead": "cic-123"}])
        assert "TEAM DISPATCHED" in guidance

    def test_shows_worker_with_bead(self):
        """Should show worker name and bead assignment."""
        guidance = get_coordinator_guidance([{"name": "Groucho", "bead": "cic-123"}])
        assert "Groucho" in guidance
        assert "cic-123" in guidance
        assert "beads workflow" in guidance

    def test_shows_worker_with_custom_prompt(self):
        """Should show worker with custom task."""
        guidance = get_coordinator_guidance([
            {"name": "Harpo", "custom_prompt": "Review the auth module"}
        ])
        assert "Harpo" in guidance
        assert "Review the auth module" in guidance

    def test_shows_worker_awaiting_task(self):
        """Should show warning for worker awaiting task."""
        guidance = get_coordinator_guidance([
            {"name": "Chico", "awaiting_task": True}
        ])
        assert "Chico" in guidance
        assert "AWAITING TASK" in guidance

    def test_shows_multiple_workers(self):
        """Should show all workers."""
        guidance = get_coordinator_guidance([
            {"name": "Groucho", "bead": "cic-123"},
            {"name": "Harpo", "custom_prompt": "Do something"},
            {"name": "Chico", "awaiting_task": True},
        ])
        assert "Groucho" in guidance
        assert "Harpo" in guidance
        assert "Chico" in guidance

    def test_includes_coordination_reminder(self):
        """Should include coordination style reminder."""
        guidance = get_coordinator_guidance([{"name": "Groucho", "bead": "cic-123"}])
        assert "Coordination style" in guidance or "Hands-off" in guidance

    def test_truncates_long_custom_prompt(self):
        """Should truncate long custom prompts."""
        long_prompt = "A" * 100
        guidance = get_coordinator_guidance([
            {"name": "Harpo", "custom_prompt": long_prompt}
        ])
        assert "..." in guidance
        # Should not contain the full 100-char string
        assert long_prompt not in guidance


class TestWorktreeMode:
    """Tests for worktree-aware prompt generation."""

    def test_worker_prompt_without_worktree_no_commit(self):
        """Worker prompt without worktree should not mention committing (unless bead)."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=False)
        # Without bead or worktree, no commit instruction
        assert "Commit when done" not in prompt

    def test_worker_prompt_with_worktree_includes_commit(self):
        """Worker prompt with worktree (no bead) should instruct committing."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=True)
        assert "Commit when done" in prompt
        assert "cherry-pick" in prompt

    def test_worker_prompt_with_bead_has_commit_in_workflow(self):
        """Worker prompt with bead has commit as part of beads workflow."""
        prompt = generate_worker_prompt("test", "Worker", bead="cic-123")
        # Commit is in the beads workflow, not separate
        assert "git commit" in prompt
        assert "cic-123" in prompt

    def test_worktree_with_bead_no_separate_commit_section(self):
        """With bead, commit is in beads workflow - no separate commit section."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=True, bead="cic-123")
        # Should have beads workflow with commit
        assert 'git commit -m "cic-123:' in prompt
        # Should NOT have separate "Commit when done" section
        assert "Commit when done" not in prompt
