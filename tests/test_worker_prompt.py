"""Tests for the worker_prompt module."""

import pytest

from claude_team_mcp.worker_prompt import (
    generate_worker_prompt,
    get_coordinator_guidance,
)


class TestGenerateWorkerPrompt:
    """Tests for generate_worker_prompt function."""

    def test_includes_session_id(self):
        """Prompt should include the session ID."""
        prompt = generate_worker_prompt("worker-abc123", "John")
        assert "worker-abc123" in prompt

    def test_includes_session_id_in_marker(self):
        """Prompt should include session ID in the marker tag."""
        prompt = generate_worker_prompt("worker-xyz", "Paul")
        assert "<!claude-team-session:worker-xyz!>" in prompt

    def test_includes_worker_name(self):
        """Prompt should address the worker by name."""
        prompt = generate_worker_prompt("worker-1", "Ringo")
        assert "Ringo" in prompt

    def test_includes_do_work_fully_rule(self):
        """Prompt should contain the 'do work fully' instruction."""
        prompt = generate_worker_prompt("test-session", "George")
        assert "Do the work fully" in prompt

    def test_includes_beads_discipline_rule(self):
        """Prompt should contain beads discipline instructions."""
        prompt = generate_worker_prompt("test-session", "TestWorker")
        assert "Beads discipline" in prompt
        assert "bd update" in prompt
        assert "bd comment" in prompt

    def test_includes_never_close_beads_instruction(self):
        """Prompt should instruct workers not to close beads."""
        prompt = generate_worker_prompt("test", "Worker")
        assert "Never close beads" in prompt

    def test_includes_bd_help_reference(self):
        """Prompt should mention bd_help tool."""
        prompt = generate_worker_prompt("test", "Worker")
        assert "bd_help" in prompt

    def test_session_id_appears_in_prompt(self):
        """Session ID should appear in the prompt (marker and reference)."""
        prompt = generate_worker_prompt("unique-id-12345", "Worker")
        # Should appear at least once in the marker
        assert "unique-id-12345" in prompt

    def test_different_sessions_produce_different_prompts(self):
        """Different session IDs should produce different prompts."""
        prompt1 = generate_worker_prompt("session-a", "Alice")
        prompt2 = generate_worker_prompt("session-b", "Bob")
        assert prompt1 != prompt2
        assert "session-a" in prompt1
        assert "session-b" in prompt2

    def test_prompt_is_non_empty_string(self):
        """Prompt should be a non-empty string."""
        prompt = generate_worker_prompt("test", "Worker")
        assert isinstance(prompt, str)
        assert len(prompt) > 100  # Should be substantial


class TestGetCoordinatorGuidance:
    """Tests for get_coordinator_guidance function."""

    def test_returns_non_empty_string(self):
        """Should return a non-empty string."""
        guidance = get_coordinator_guidance()
        assert isinstance(guidance, str)
        assert len(guidance) > 0

    def test_contains_coordinator_marker(self):
        """Guidance should identify the coordinator role."""
        guidance = get_coordinator_guidance()
        assert "COORDINATOR" in guidance

    def test_mentions_list_sessions(self):
        """Guidance should mention list_sessions command."""
        guidance = get_coordinator_guidance()
        assert "list_sessions" in guidance

    def test_mentions_is_idle(self):
        """Guidance should mention is_idle command."""
        guidance = get_coordinator_guidance()
        assert "is_idle" in guidance

    def test_mentions_annotate_session(self):
        """Guidance should mention annotate_session command."""
        guidance = get_coordinator_guidance()
        assert "annotate_session" in guidance

    def test_mentions_get_conversation_history(self):
        """Guidance should mention get_conversation_history command."""
        guidance = get_coordinator_guidance()
        assert "get_conversation_history" in guidance

    def test_mentions_idle_detection(self):
        """Guidance should explain idle detection."""
        guidance = get_coordinator_guidance()
        assert "idle" in guidance.lower()

    def test_mentions_reviewing_beads(self):
        """Guidance should mention reviewing and closing beads."""
        guidance = get_coordinator_guidance()
        assert "close bead" in guidance.lower() or "close" in guidance


class TestWorktreeMode:
    """Tests for worktree-aware prompt generation."""

    def test_worker_prompt_without_worktree_no_commit(self):
        """Worker prompt without worktree should not mention committing."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=False)
        assert "Commit when done" not in prompt

    def test_worker_prompt_with_worktree_includes_commit(self):
        """Worker prompt with worktree should instruct committing."""
        prompt = generate_worker_prompt("test", "Worker", use_worktree=True)
        assert "Commit when done" in prompt
        assert "cherry-pick" in prompt

    def test_coordinator_guidance_without_worktree_no_commit(self):
        """Coordinator guidance without worktree should not mention commit."""
        guidance = get_coordinator_guidance(use_worktree=False)
        assert "cherry-picking" not in guidance

    def test_coordinator_guidance_with_worktree_includes_commit(self):
        """Coordinator guidance with worktree should mention commit."""
        guidance = get_coordinator_guidance(use_worktree=True)
        assert "cherry-picking" in guidance

    def test_coordinator_guidance_contains_expectations(self):
        """Should describe what workers have been told."""
        guidance = get_coordinator_guidance()
        assert "What workers have been told" in guidance

    def test_coordinator_guidance_contains_responsibilities(self):
        """Should list coordinator responsibilities."""
        guidance = get_coordinator_guidance()
        assert "responsibilities" in guidance.lower()


class TestItermMarker:
    """Tests for iTerm-specific marker functionality."""

    def test_no_iterm_marker_by_default(self):
        """Prompt should not include iTerm marker when not provided."""
        prompt = generate_worker_prompt("test-session", "Worker")
        assert "<!claude-team-iterm:" not in prompt

    def test_includes_iterm_marker_when_provided(self):
        """Prompt should include iTerm marker when iterm_session_id is provided."""
        prompt = generate_worker_prompt(
            "test-session",
            "Worker",
            iterm_session_id="ABC123-DEF456",
        )
        assert "<!claude-team-iterm:ABC123-DEF456!>" in prompt

    def test_both_markers_present_when_iterm_id_provided(self):
        """Both internal and iTerm markers should be present."""
        prompt = generate_worker_prompt(
            "internal-id",
            "Worker",
            iterm_session_id="iterm-id",
        )
        assert "<!claude-team-session:internal-id!>" in prompt
        assert "<!claude-team-iterm:iterm-id!>" in prompt

    def test_iterm_marker_with_worktree(self):
        """iTerm marker should work alongside worktree mode."""
        prompt = generate_worker_prompt(
            "test",
            "Worker",
            use_worktree=True,
            iterm_session_id="iterm-123",
        )
        assert "<!claude-team-iterm:iterm-123!>" in prompt
        assert "Commit when done" in prompt
