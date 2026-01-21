"""Tests for the worker_prompt module."""

import pytest

from claude_team_mcp.worker_prompt import (
    AgentType,
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

    def test_case1_issue_only(self, tmp_path):
        """With issue only, should show assignment and tracker workflow."""
        # Create a project with pebbles marker for testing
        project_path = tmp_path / "test-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        issue_id = "cic-123"
        prompt = generate_worker_prompt(
            "test", "Worker",
            bead=issue_id,
            project_path=str(project_path)
        )
        assert f"Your assignment is `{issue_id}`" in prompt
        assert "workflow" in prompt
        assert "Mark in progress" in prompt
        assert "Close issue" in prompt
        assert "Get to work!" in prompt

    def test_case2_issue_and_custom_prompt(self):
        """With issue and custom prompt, should show both."""
        issue_id = "cic-456"
        prompt = generate_worker_prompt(
            "test", "Worker",
            bead=issue_id,
            custom_prompt="Focus on the edge cases"
        )
        assert f"`{issue_id}`" in prompt
        assert "Focus on the edge cases" in prompt
        assert "workflow" in prompt
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
        # Should not have tracker workflow
        assert "workflow" not in prompt

    def test_case4_no_issue_no_prompt(self):
        """With neither issue nor prompt, should say coordinator will message."""
        prompt = generate_worker_prompt("test", "Worker")
        assert "The coordinator will send your first task shortly" in prompt
        # Should not have assignment section
        assert "YOUR ASSIGNMENT" not in prompt
        assert "workflow" not in prompt


class TestIssueTrackerWorkflow:
    """Tests for issue tracker workflow instructions."""

    def test_workflow_includes_update_and_close(self, tmp_path):
        """Workflow should include update and close commands."""
        # Create a project with pebbles marker for testing
        project_path = tmp_path / "test-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        issue_id = "cic-abc"
        prompt = generate_worker_prompt(
            "test", "Worker",
            bead=issue_id,
            project_path=str(project_path)
        )
        assert f"update {issue_id}" in prompt
        assert f"close {issue_id}" in prompt
        assert "status in_progress" in prompt

    def test_workflow_includes_commit_instruction(self, tmp_path):
        """Workflow should include commit with issue reference."""
        # Create a project with pebbles marker for testing
        project_path = tmp_path / "test-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        issue_id = "cic-abc"
        prompt = generate_worker_prompt(
            "test", "Worker",
            bead=issue_id,
            project_path=str(project_path)
        )
        assert f'git commit -m "{issue_id}:' in prompt


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

    def test_shows_worker_with_issue(self):
        """Should show worker name and issue assignment."""
        guidance = get_coordinator_guidance([{"name": "Groucho", "bead": "cic-123"}])
        assert "Groucho" in guidance
        assert "cic-123" in guidance
        assert "mark in_progress" in guidance

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
        """Worker prompt without worktree should not mention committing (unless issue)."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=False)
        # Without issue or worktree, no commit instruction
        assert "Commit when done" not in prompt

    def test_worker_prompt_with_worktree_includes_commit(self):
        """Worker prompt with worktree (no issue) should instruct committing."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=True)
        assert "Commit when done" in prompt
        assert "cherry-pick" in prompt

    def test_worker_prompt_with_issue_has_commit_in_workflow(self):
        """Worker prompt with issue has commit as part of tracker workflow."""
        prompt = generate_worker_prompt("test", "Worker", bead="cic-123")
        # Commit is in the tracker workflow, not separate
        assert "git commit" in prompt
        assert "cic-123" in prompt

    def test_worktree_with_issue_no_separate_commit_section(self):
        """With issue, commit is in tracker workflow - no separate commit section."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=True, bead="cic-123")
        # Should have tracker workflow with commit
        assert 'git commit -m "cic-123:' in prompt
        # Should NOT have separate "Commit when done" section
        assert "Commit when done" not in prompt


class TestAgentTypeParameter:
    """Tests for agent_type parameter in generate_worker_prompt."""

    def test_default_agent_type_is_claude(self):
        """Default agent_type should be claude."""
        prompt = generate_worker_prompt("test", "Worker")
        # Claude prompt has "claude-team" reference
        assert "claude-team" in prompt

    def test_explicit_claude_agent_type(self):
        """Explicit claude agent_type should produce Claude prompt."""
        prompt = generate_worker_prompt("test", "Worker", agent_type="claude")
        assert "claude-team" in prompt
        assert "automatically report" in prompt

    def test_codex_agent_type_produces_different_prompt(self):
        """Codex agent_type should produce Codex-specific prompt."""
        prompt = generate_worker_prompt("test", "Worker", agent_type="codex")
        # Codex prompt should NOT have claude-team specific references
        assert "claude-team" not in prompt
        # Codex prompt should have different completion detection instructions
        assert "COMPLETED" in prompt or "BLOCKED" in prompt


class TestCodexWorkerPrompt:
    """Tests for Codex-specific worker prompt generation."""

    def test_codex_includes_worker_name(self):
        """Codex prompt should address the worker by name."""
        prompt = generate_worker_prompt("test", "Zeppo", agent_type="codex")
        assert "Zeppo" in prompt

    def test_codex_has_no_mcp_markers(self):
        """Codex prompt should not reference MCP markers."""
        prompt = generate_worker_prompt("test", "Worker", agent_type="codex")
        assert "claude-team" not in prompt
        assert "automatically report your session" not in prompt

    def test_codex_has_status_completion_instructions(self):
        """Codex prompt should instruct to end with COMPLETED or BLOCKED."""
        prompt = generate_worker_prompt("test", "Worker", agent_type="codex")
        assert "COMPLETED" in prompt
        assert "BLOCKED" in prompt

    def test_codex_tracker_workflow_same_as_claude(self, tmp_path):
        """Codex tracker workflow should match Claude's."""
        # Create a project with pebbles marker for testing
        project_path = tmp_path / "test-repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()

        issue_id = "cic-123"
        codex_prompt = generate_worker_prompt(
            "test", "Worker",
            agent_type="codex",
            bead=issue_id,
            project_path=str(project_path)
        )
        claude_prompt = generate_worker_prompt(
            "test", "Worker",
            agent_type="claude",
            bead=issue_id,
            project_path=str(project_path)
        )
        for prompt in (codex_prompt, claude_prompt):
            assert f"update {issue_id}" in prompt
            assert f"close {issue_id}" in prompt
            assert "status in_progress" in prompt

    def test_codex_with_issue_only(self):
        """Codex with issue only should show assignment."""
        issue_id = "cic-456"
        prompt = generate_worker_prompt("test", "Worker", agent_type="codex", bead=issue_id)
        assert f"Your assignment is `{issue_id}`" in prompt
        assert "workflow" in prompt
        assert "Mark in progress" in prompt

    def test_codex_with_custom_prompt(self):
        """Codex with custom prompt should show the task."""
        prompt = generate_worker_prompt(
            "test", "Worker",
            agent_type="codex",
            custom_prompt="Fix the auth bug"
        )
        assert "Fix the auth bug" in prompt
        assert "The coordinator assigned you the following task" in prompt

    def test_codex_with_worktree_includes_commit(self):
        """Codex with worktree should include commit instructions."""
        prompt = generate_worker_prompt(
            "test", "Worker",
            agent_type="codex",
            use_worktree=True
        )
        assert "Commit when done" in prompt
        assert "cherry-pick" in prompt


class TestMixedTeamCoordinatorGuidance:
    """Tests for coordinator guidance with mixed Claude/Codex teams."""

    def test_single_agent_type_no_indicator(self):
        """With only one agent type, no [type] indicator should appear."""
        guidance = get_coordinator_guidance([
            {"name": "Groucho", "bead": "cic-123", "agent_type": "claude"},
            {"name": "Harpo", "bead": "cic-456", "agent_type": "claude"},
        ])
        assert "[claude]" not in guidance
        assert "[codex]" not in guidance

    def test_mixed_team_shows_type_indicators(self):
        """With mixed team, should show [type] indicators."""
        guidance = get_coordinator_guidance([
            {"name": "Groucho", "bead": "cic-123", "agent_type": "claude"},
            {"name": "GPT-4", "bead": "cic-456", "agent_type": "codex"},
        ])
        assert "[claude]" in guidance
        assert "[codex]" in guidance

    def test_mixed_team_shows_guidance_note(self):
        """Mixed team should include guidance about different idle detection."""
        guidance = get_coordinator_guidance([
            {"name": "Groucho", "agent_type": "claude", "bead": "cic-123"},
            {"name": "Codex-1", "agent_type": "codex", "bead": "cic-456"},
        ])
        assert "Mixed team note" in guidance
        assert "Claude workers" in guidance
        assert "Codex workers" in guidance

    def test_default_agent_type_is_claude(self):
        """Workers without explicit agent_type should default to claude."""
        guidance = get_coordinator_guidance([
            {"name": "Groucho", "bead": "cic-123"},  # No agent_type
            {"name": "Codex-1", "agent_type": "codex", "bead": "cic-456"},
        ])
        # Should still be mixed team because one is explicitly codex
        assert "[claude]" in guidance
        assert "[codex]" in guidance

    def test_codex_only_team_no_mixed_note(self):
        """Codex-only team should not show mixed team note."""
        guidance = get_coordinator_guidance([
            {"name": "Codex-1", "agent_type": "codex", "bead": "cic-123"},
            {"name": "Codex-2", "agent_type": "codex", "bead": "cic-456"},
        ])
        assert "Mixed team note" not in guidance
        # Should still not show type indicators (not mixed)
        assert "[codex]" not in guidance
