"""Tests for session_state module - iTerm marker functionality."""

from claude_team_mcp.session_state import (
    ITERM_MARKER_PREFIX,
    ITERM_MARKER_SUFFIX,
    MARKER_PREFIX,
    MARKER_SUFFIX,
    extract_iterm_session_id,
    extract_marker_session_id,
    generate_marker_message,
)


class TestMarkerConstants:
    """Test marker constant definitions."""

    def test_internal_marker_format(self):
        """Internal marker should use claude-team-session format."""
        assert MARKER_PREFIX == "<!claude-team-session:"
        assert MARKER_SUFFIX == "!>"

    def test_iterm_marker_format(self):
        """iTerm marker should use claude-team-iterm format."""
        assert ITERM_MARKER_PREFIX == "<!claude-team-iterm:"
        assert ITERM_MARKER_SUFFIX == "!>"


class TestExtractMarkerSessionId:
    """Tests for extract_marker_session_id function."""

    def test_extracts_session_id(self):
        """Should extract session ID from marker text."""
        text = "Some text <!claude-team-session:abc123!> more text"
        assert extract_marker_session_id(text) == "abc123"

    def test_returns_none_for_no_marker(self):
        """Should return None when no marker present."""
        text = "No marker here"
        assert extract_marker_session_id(text) is None

    def test_returns_none_for_incomplete_marker(self):
        """Should return None for incomplete marker."""
        text = "<!claude-team-session:abc123 no closing"
        assert extract_marker_session_id(text) is None

    def test_handles_uuid_format(self):
        """Should handle UUID-style session IDs."""
        text = "<!claude-team-session:550e8400-e29b-41d4-a716-446655440000!>"
        assert extract_marker_session_id(text) == "550e8400-e29b-41d4-a716-446655440000"


class TestExtractItermSessionId:
    """Tests for extract_iterm_session_id function."""

    def test_extracts_iterm_session_id(self):
        """Should extract iTerm session ID from marker text."""
        text = "Some text <!claude-team-iterm:ABC-DEF-123!> more text"
        assert extract_iterm_session_id(text) == "ABC-DEF-123"

    def test_returns_none_for_no_marker(self):
        """Should return None when no iTerm marker present."""
        text = "No marker here"
        assert extract_iterm_session_id(text) is None

    def test_returns_none_for_wrong_marker_type(self):
        """Should return None for internal marker (not iTerm)."""
        text = "<!claude-team-session:abc123!>"
        assert extract_iterm_session_id(text) is None

    def test_handles_iterm_uuid_format(self):
        """Should handle iTerm2's UUID format."""
        text = "<!claude-team-iterm:C67C391C-7605-43A3-A6A2-F8A577049271!>"
        assert extract_iterm_session_id(text) == "C67C391C-7605-43A3-A6A2-F8A577049271"

    def test_extracts_iterm_when_both_markers_present(self):
        """Should extract iTerm ID when both markers are present."""
        text = """<!claude-team-session:internal-123!>
<!claude-team-iterm:ITERM-ABC-456!>
More content here"""
        assert extract_iterm_session_id(text) == "ITERM-ABC-456"
        assert extract_marker_session_id(text) == "internal-123"


class TestGenerateMarkerMessage:
    """Tests for generate_marker_message function."""

    def test_includes_internal_marker(self):
        """Message should include internal session marker."""
        message = generate_marker_message("abc123")
        assert "<!claude-team-session:abc123!>" in message

    def test_no_iterm_marker_by_default(self):
        """Message should not include iTerm marker when not provided."""
        message = generate_marker_message("abc123")
        assert "<!claude-team-iterm:" not in message

    def test_includes_iterm_marker_when_provided(self):
        """Message should include iTerm marker when iterm_session_id provided."""
        message = generate_marker_message("abc123", iterm_session_id="ITERM-XYZ")
        assert "<!claude-team-iterm:ITERM-XYZ!>" in message

    def test_both_markers_when_iterm_provided(self):
        """Message should include both markers when iTerm ID provided."""
        message = generate_marker_message("internal-id", iterm_session_id="iterm-id")
        assert "<!claude-team-session:internal-id!>" in message
        assert "<!claude-team-iterm:iterm-id!>" in message

    def test_includes_identification_instruction(self):
        """Message should instruct Claude to respond with 'Identified!'."""
        message = generate_marker_message("test")
        assert "Identified!" in message
