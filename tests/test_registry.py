"""Tests for the session registry module."""

from unittest.mock import MagicMock

from claude_team_mcp.registry import (
    ManagedSession,
    SessionRegistry,
    SessionStatus,
)


class TestSessionRegistryBasics:
    """Basic tests for SessionRegistry functionality."""

    def test_add_creates_session(self):
        """add should create and return a ManagedSession."""
        registry = SessionRegistry()
        mock_iterm = MagicMock()

        session = registry.add(mock_iterm, "/test/path", name="TestWorker")

        assert session is not None
        assert session.name == "TestWorker"
        assert session.project_path == "/test/path"

    def test_get_returns_session(self):
        """get should return session by ID."""
        registry = SessionRegistry()
        mock_iterm = MagicMock()

        session = registry.add(mock_iterm, "/test/path")
        retrieved = registry.get(session.session_id)

        assert retrieved is session

    def test_get_returns_none_for_unknown(self):
        """get should return None for unknown session ID."""
        registry = SessionRegistry()
        assert registry.get("nonexistent") is None

    def test_count_returns_session_count(self):
        """count should return number of sessions."""
        registry = SessionRegistry()
        mock_iterm = MagicMock()

        assert registry.count() == 0
        registry.add(mock_iterm, "/path/a")
        assert registry.count() == 1
        registry.add(mock_iterm, "/path/b")
        assert registry.count() == 2

    def test_list_all_returns_all_sessions(self):
        """list_all should return all registered sessions."""
        registry = SessionRegistry()
        mock_iterm = MagicMock()

        session_a = registry.add(mock_iterm, "/path/a")
        session_b = registry.add(mock_iterm, "/path/b")

        all_sessions = registry.list_all()
        assert len(all_sessions) == 2
        assert session_a in all_sessions
        assert session_b in all_sessions

    def test_remove_removes_session(self):
        """remove should remove session from registry."""
        registry = SessionRegistry()
        mock_iterm = MagicMock()

        session = registry.add(mock_iterm, "/test/path")
        registry.remove(session.session_id)

        assert registry.get(session.session_id) is None
        assert registry.count() == 0


class TestManagedSessionToDict:
    """Tests for ManagedSession.to_dict() output format."""

    def test_to_dict_contains_source_field(self):
        """to_dict() includes source='registry' field for live sessions."""
        mock_iterm = MagicMock()
        session = ManagedSession(
            session_id="test-123",
            terminal_session=mock_iterm,
            project_path="/test/path",
            name="TestWorker",
        )

        d = session.to_dict()
        assert d["source"] == "registry"

    def test_to_dict_contains_core_fields(self):
        """to_dict() includes all expected fields."""
        mock_iterm = MagicMock()
        session = ManagedSession(
            session_id="test-123",
            terminal_session=mock_iterm,
            project_path="/test/path",
            name="TestWorker",
        )

        d = session.to_dict()

        # Verify core fields are present
        assert d["session_id"] == "test-123"
        assert d["name"] == "TestWorker"
        assert d["project_path"] == "/test/path"
        assert d["status"] == "spawning"
        assert d["agent_type"] == "claude"
        assert "created_at" in d
        assert "last_activity" in d
        # Source field distinguishes live from recovered sessions
        assert d["source"] == "registry"
