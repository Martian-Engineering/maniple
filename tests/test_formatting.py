"""Tests for formatting utilities."""

from maniple_mcp.formatting import format_badge_text, format_session_title


class TestFormatSessionTitle:
    """Tests for format_session_title function."""

    def test_full_title_with_all_parts(self):
        """Test with session name, issue ID, and badge."""
        result = format_session_title("worker-1", "cic-3dj", "profile module")
        assert result == "[worker-1] cic-3dj: profile module"

    def test_title_with_issue_id_only(self):
        """Test with session name and issue ID, no badge."""
        result = format_session_title("worker-2", issue_id="cic-abc")
        assert result == "[worker-2] cic-abc"

    def test_title_with_badge_only(self):
        """Test with session name and badge, no issue ID."""
        result = format_session_title("worker-3", badge="refactor auth")
        assert result == "[worker-3] refactor auth"

    def test_title_with_annotation_alias_only(self):
        """Legacy annotation alias should still be accepted."""
        result = format_session_title("worker-3", annotation="refactor auth")
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
        # Empty issue_id with badge
        result = format_session_title("worker-6", "", "some task")
        assert result == "[worker-6] some task"


class TestFormatBadgeText:
    """Tests for format_badge_text function."""

    def test_badge_with_issue_id_and_badge_text(self):
        """Test multi-line badge with issue ID and badge text."""
        result = format_badge_text("Groucho", "cic-3dj", "profile module")
        assert result == "cic-3dj\nprofile module"

    def test_badge_with_name_and_badge_text(self):
        """Test multi-line badge with name and badge text (no issue ID)."""
        result = format_badge_text("Groucho", badge="quick task")
        assert result == "Groucho\nquick task"

    def test_badge_with_annotation_alias(self):
        """Legacy annotation alias should still be accepted."""
        result = format_badge_text("Groucho", annotation="quick task")
        assert result == "Groucho\nquick task"

    def test_badge_prefers_badge_over_annotation_alias(self):
        """When both are provided, badge should take precedence."""
        result = format_badge_text("Groucho", badge="new", annotation="old")
        assert result == "Groucho\nnew"

    def test_badge_with_issue_id_only(self):
        """Test single-line badge with just issue ID."""
        result = format_badge_text("Groucho", issue_id="cic-xyz")
        assert result == "cic-xyz"

    def test_badge_with_name_only(self):
        """Test single-line badge with just name."""
        result = format_badge_text("Groucho")
        assert result == "Groucho"

    def test_badge_issue_id_takes_precedence_over_name(self):
        """Test that issue ID is shown on first line when provided, not name."""
        result = format_badge_text("Groucho", issue_id="cic-abc")
        assert result == "cic-abc"
        assert "Groucho" not in result

    def test_badge_newline_separator(self):
        """Test that multi-line badge uses newline separator."""
        result = format_badge_text("Worker", issue_id="cic-123", badge="task")
        assert "\n" in result
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "cic-123"
        assert lines[1] == "task"

    def test_badge_empty_issue_id_uses_name(self):
        """Test that empty string issue_id falls back to name."""
        result = format_badge_text("Groucho", issue_id="", badge="task")
        assert result == "Groucho\ntask"

    def test_badge_none_issue_id_uses_name(self):
        """Test that None issue_id falls back to name."""
        result = format_badge_text("Groucho", issue_id=None, badge="task")
        assert result == "Groucho\ntask"

    def test_badge_text_truncation(self):
        """Test that long badge text is truncated with ellipsis."""
        long_badge = "implement user authentication system with OAuth"
        result = format_badge_text("Groucho", badge=long_badge, max_badge_length=30)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[1].endswith("...")
        assert len(lines[1]) == 30

    def test_badge_text_exact_length(self):
        """Test badge text exactly at max length is not truncated."""
        badge = "a" * 30
        result = format_badge_text("Groucho", badge=badge, max_badge_length=30)
        lines = result.split("\n")
        assert lines[1] == badge
        assert "..." not in lines[1]

    def test_badge_text_one_over(self):
        """Test badge text one char over max length is truncated."""
        badge = "a" * 31
        result = format_badge_text("Groucho", badge=badge, max_badge_length=30)
        lines = result.split("\n")
        assert lines[1].endswith("...")
        assert len(lines[1]) == 30

    def test_badge_custom_max_length(self):
        """Test custom max_badge_length parameter."""
        badge = "this is a moderately long badge"
        result = format_badge_text("Groucho", badge=badge, max_badge_length=20)
        lines = result.split("\n")
        assert len(lines[1]) == 20
        assert lines[1] == "this is a moderat..."

    def test_badge_default_max_length(self):
        """Test default max_badge_length is 30."""
        badge = "a" * 35
        result = format_badge_text("Groucho", badge=badge)
        lines = result.split("\n")
        assert len(lines[1]) == 30

    def test_badge_max_annotation_length_alias(self):
        """Legacy max_annotation_length alias should still be accepted."""
        badge = "a" * 35
        result = format_badge_text("Groucho", badge=badge, max_annotation_length=20)
        lines = result.split("\n")
        assert len(lines[1]) == 20

    def test_badge_first_line_not_truncated(self):
        """Test that first line (issue_id/name) is never truncated."""
        long_issue_id = "cic-very-long-issue-id-here"
        result = format_badge_text("Groucho", issue_id=long_issue_id)
        assert result == long_issue_id
