"""Tests for the worktree module."""

from maniple_mcp.worktree import short_slug


class TestShortSlug:
    """Tests for short_slug function."""

    def test_empty_string_returns_empty(self):
        """Empty input should return empty string."""
        assert short_slug("") == ""

    def test_all_special_chars_returns_empty(self):
        """All special chars should slugify to empty string."""
        assert short_slug("!!!@@@") == ""

    def test_exact_max_length_passthrough(self):
        """Input matching max length should not be truncated."""
        text = "a" * 30
        assert short_slug(text) == text

    def test_truncation_strips_trailing_hyphen(self):
        """Truncated slug should not end with a hyphen."""
        text = ("a" * 29) + "-" + "b"
        assert short_slug(text) == "a" * 29

    def test_shorter_than_max_passthrough(self):
        """Short input should return slugified text unchanged."""
        assert short_slug("Short Slug") == "short-slug"
