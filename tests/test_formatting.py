"""Tests for formatting utilities."""

import pytest

from claude_team_mcp.formatting import format_session_title, format_badge_text


class TestFormatSessionTitle:
    """Tests for format_session_title function."""

    def test_full_title_with_all_parts(self):
        """Test with session name, issue ID, and task description."""
        result = format_session_title("worker-1", "cic-3dj", "profile module")
        assert result == "[worker-1] cic-3dj: profile module"

    def test_title_with_issue_id_only(self):
        """Test with session name and issue ID, no description."""
        result = format_session_title("worker-2", issue_id="cic-abc")
        assert result == "[worker-2] cic-abc"

    def test_title_with_task_desc_only(self):
        """Test with session name and description, no issue ID."""
        result = format_session_title("worker-3", task_desc="refactor auth")
        assert result == "[worker-3] refactor auth"

    def test_title_with_session_name_only(self):
        """Test with just session name."""
        result = format_session_title("worker-4")
        assert result == "[worker-4]"

    def test_title_with_none_values(self):
        """Test explicit None values."""
        result = format_session_title("worker-5", None, None)
        assert result == "[worker-5]"

    def test_title_with_empty_strings(self):
        """Empty strings should be treated like None."""
        # Empty issue_id with task_desc
        result = format_session_title("worker-6", "", "some task")
        assert result == "[worker-6] some task"


class TestFormatBadgeText:
    """Tests for format_badge_text function."""

    def test_badge_with_both_parts_short(self):
        """Test short text that doesn't need truncation."""
        result = format_badge_text("cic-3dj", "profile module", max_length=25)
        assert result == "cic-3dj: profile module"

    def test_badge_truncation(self):
        """Test that long text is truncated with ellipsis."""
        result = format_badge_text(
            "cic-3dj", "implement user authentication system", max_length=25
        )
        assert len(result) == 25
        assert result.endswith("...")
        assert result == "cic-3dj: implement use..."

    def test_badge_issue_id_only(self):
        """Test with just issue ID."""
        result = format_badge_text(issue_id="cic-xyz", max_length=25)
        assert result == "cic-xyz"

    def test_badge_task_desc_only(self):
        """Test with just task description."""
        result = format_badge_text(task_desc="quick fix", max_length=25)
        assert result == "quick fix"

    def test_badge_empty(self):
        """Test with no inputs returns empty string."""
        result = format_badge_text()
        assert result == ""

    def test_badge_exact_length(self):
        """Test text that's exactly max_length."""
        result = format_badge_text(task_desc="a" * 25, max_length=25)
        assert result == "a" * 25
        assert len(result) == 25

    def test_badge_one_over_length(self):
        """Test text that's one char over max_length."""
        result = format_badge_text(task_desc="a" * 26, max_length=25)
        assert len(result) == 25
        assert result.endswith("...")

    def test_badge_very_short_max_length(self):
        """Test with very short max_length enforces minimum."""
        result = format_badge_text(task_desc="hello", max_length=2)
        # Should enforce minimum of 4
        assert len(result) == 4
        assert result == "h..."

    def test_badge_default_max_length(self):
        """Test that default max_length is 25."""
        long_text = "a" * 30
        result = format_badge_text(task_desc=long_text)
        assert len(result) == 25
