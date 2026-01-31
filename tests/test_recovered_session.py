"""Tests for RecoveredSession dataclass."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from claude_team_mcp.registry import (
    AnySession,
    EventState,
    RecoveredSession,
    SessionSource,
    SessionStatus,
    TerminalId,
)


class TestRecoveredSessionConstruction:
    """Tests for RecoveredSession construction from snapshot data."""

    def test_construction_with_required_fields(self):
        """RecoveredSession can be constructed with all required fields."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=TerminalId("iterm", "ABC-123"),
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
        )

        assert session.session_id == "abc12345"
        assert session.name == "Groucho"
        assert session.project_path == "/Users/test/project"
        assert session.terminal_id == TerminalId("iterm", "ABC-123")
        assert session.agent_type == "claude"
        assert session.status == SessionStatus.READY
        assert session.event_state == "idle"

    def test_construction_with_optional_fields(self):
        """RecoveredSession accepts optional fields from snapshot."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="def67890",
            name="Harpo",
            project_path="/Users/test/project2",
            terminal_id=TerminalId("tmux", "%1"),
            agent_type="codex",
            status=SessionStatus.BUSY,
            last_activity=now,
            created_at=now,
            event_state="active",
            recovered_at=now,
            last_event_ts=now,
            claude_session_id="session-uuid-123",
            coordinator_annotation="Working on auth refactor",
            worktree_path="/Users/test/project2/.worktrees/feature-branch",
            main_repo_path="/Users/test/project2",
        )

        assert session.claude_session_id == "session-uuid-123"
        assert session.coordinator_annotation == "Working on auth refactor"
        assert session.worktree_path == "/Users/test/project2/.worktrees/feature-branch"
        assert session.main_repo_path == "/Users/test/project2"

    def test_construction_with_none_terminal_id(self):
        """RecoveredSession accepts None terminal_id."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="xyz99999",
            name="Chico",
            project_path="/Users/test/project",
            terminal_id=None,
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
        )

        assert session.terminal_id is None


class TestRecoveredSessionToDict:
    """Tests for RecoveredSession.to_dict() output format."""

    @pytest.fixture
    def sample_session(self):
        """Create a sample RecoveredSession for testing."""
        now = datetime(2026, 1, 31, 12, 0, 0)
        return RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=TerminalId("iterm", "ABC-123"),
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
            claude_session_id="session-uuid",
            coordinator_annotation="Test annotation",
            worktree_path="/path/to/worktree",
            main_repo_path="/path/to/repo",
        )

    def test_to_dict_contains_core_fields(self, sample_session):
        """to_dict() includes all core fields matching ManagedSession format."""
        d = sample_session.to_dict()

        assert d["session_id"] == "abc12345"
        assert d["name"] == "Groucho"
        assert d["project_path"] == "/Users/test/project"
        assert d["terminal_id"] == "iterm:ABC-123"
        assert d["agent_type"] == "claude"
        assert d["status"] == "ready"
        assert d["claude_session_id"] == "session-uuid"
        assert d["coordinator_annotation"] == "Test annotation"
        assert d["worktree_path"] == "/path/to/worktree"
        assert d["main_repo_path"] == "/path/to/repo"

    def test_to_dict_contains_source_field(self, sample_session):
        """to_dict() includes source='event_log' field."""
        d = sample_session.to_dict()
        assert d["source"] == "event_log"

    def test_to_dict_contains_event_state_field(self, sample_session):
        """to_dict() includes event_state field."""
        d = sample_session.to_dict()
        assert d["event_state"] == "idle"

    def test_to_dict_contains_recovered_at_field(self, sample_session):
        """to_dict() includes recovered_at as ISO timestamp."""
        d = sample_session.to_dict()
        assert d["recovered_at"] == "2026-01-31T12:00:00"

    def test_to_dict_contains_last_event_ts_field(self, sample_session):
        """to_dict() includes last_event_ts as ISO timestamp."""
        d = sample_session.to_dict()
        assert d["last_event_ts"] == "2026-01-31T12:00:00"

    def test_to_dict_timestamps_are_iso_format(self, sample_session):
        """to_dict() returns timestamps in ISO format."""
        d = sample_session.to_dict()
        assert d["created_at"] == "2026-01-31T12:00:00"
        assert d["last_activity"] == "2026-01-31T12:00:00"
        assert d["recovered_at"] == "2026-01-31T12:00:00"
        assert d["last_event_ts"] == "2026-01-31T12:00:00"

    def test_to_dict_with_none_terminal_id(self):
        """to_dict() handles None terminal_id correctly."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=None,
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
        )
        d = session.to_dict()
        assert d["terminal_id"] is None


class TestRecoveredSessionIsIdle:
    """Tests for RecoveredSession.is_idle() based on event_state."""

    def test_is_idle_returns_true_for_idle_state(self):
        """is_idle() returns True when event_state is 'idle'."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=None,
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
        )
        assert session.is_idle() is True

    def test_is_idle_returns_false_for_active_state(self):
        """is_idle() returns False when event_state is 'active'."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=None,
            agent_type="claude",
            status=SessionStatus.BUSY,
            last_activity=now,
            created_at=now,
            event_state="active",
            recovered_at=now,
            last_event_ts=now,
        )
        assert session.is_idle() is False

    def test_is_idle_returns_false_for_closed_state(self):
        """is_idle() returns False when event_state is 'closed'."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=None,
            agent_type="claude",
            status=SessionStatus.BUSY,
            last_activity=now,
            created_at=now,
            event_state="closed",
            recovered_at=now,
            last_event_ts=now,
        )
        assert session.is_idle() is False


class TestRecoveredSessionStateMapping:
    """Tests for RecoveredSession.map_event_state_to_status()."""

    def test_idle_maps_to_ready(self):
        """Event state 'idle' maps to SessionStatus.READY."""
        result = RecoveredSession.map_event_state_to_status("idle")
        assert result == SessionStatus.READY

    def test_active_maps_to_busy(self):
        """Event state 'active' maps to SessionStatus.BUSY."""
        result = RecoveredSession.map_event_state_to_status("active")
        assert result == SessionStatus.BUSY

    def test_closed_maps_to_busy(self):
        """Event state 'closed' maps to SessionStatus.BUSY."""
        result = RecoveredSession.map_event_state_to_status("closed")
        assert result == SessionStatus.BUSY


class TestRecoveredSessionFrozenImmutability:
    """Tests for RecoveredSession frozen dataclass immutability."""

    @pytest.fixture
    def frozen_session(self):
        """Create a frozen RecoveredSession for testing."""
        now = datetime.now()
        return RecoveredSession(
            session_id="abc12345",
            name="Groucho",
            project_path="/Users/test/project",
            terminal_id=TerminalId("iterm", "ABC-123"),
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
        )

    def test_cannot_modify_session_id(self, frozen_session):
        """Cannot modify session_id on frozen dataclass."""
        with pytest.raises(FrozenInstanceError):
            frozen_session.session_id = "new_id"

    def test_cannot_modify_name(self, frozen_session):
        """Cannot modify name on frozen dataclass."""
        with pytest.raises(FrozenInstanceError):
            frozen_session.name = "Harpo"

    def test_cannot_modify_status(self, frozen_session):
        """Cannot modify status on frozen dataclass."""
        with pytest.raises(FrozenInstanceError):
            frozen_session.status = SessionStatus.BUSY

    def test_cannot_modify_event_state(self, frozen_session):
        """Cannot modify event_state on frozen dataclass."""
        with pytest.raises(FrozenInstanceError):
            frozen_session.event_state = "active"


class TestTypeAliases:
    """Tests for type aliases defined in registry module."""

    def test_event_state_type_alias_exists(self):
        """EventState type alias is importable."""
        # Type alias existence is validated by import at top of file
        assert EventState is not None

    def test_session_source_type_alias_exists(self):
        """SessionSource type alias is importable."""
        assert SessionSource is not None

    def test_any_session_type_alias_exists(self):
        """AnySession type alias is importable."""
        assert AnySession is not None
