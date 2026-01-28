"""Tests for worker poller snapshot diffing."""

from claude_team.poller import _build_snapshot, _build_transition_events


class _FakeSession:
    """Minimal session stub for poller diff tests."""

    def __init__(self, session_id: str, idle: bool, agent_type: str = "claude") -> None:
        """Initialize with a session id, idle state, and agent type."""
        self.session_id = session_id
        self._idle = idle
        self.agent_type = agent_type
        self.project_path = ""
        self.claude_session_id = None

    def is_idle(self) -> bool:
        """Return whether the session is idle."""
        return self._idle

    def to_dict(self) -> dict:
        """Return a minimal serialized representation of the session."""
        return {"session_id": self.session_id}


class _FakeRegistry:
    """Registry stub that returns a predefined set of sessions."""

    def __init__(self, sessions: list[_FakeSession]) -> None:
        """Initialize with a list of sessions."""
        self._sessions = sessions

    def list_all(self) -> list[_FakeSession]:
        """Return all sessions in the registry."""
        return list(self._sessions)


def _snapshot_for(*sessions: _FakeSession) -> dict:
    # Build a snapshot from a set of fake sessions.
    return _build_snapshot(_FakeRegistry(list(sessions)))


class TestPollerTransitions:
    """Transition detection for worker snapshots."""

    def test_new_worker_emits_started_once(self) -> None:
        """New worker should emit worker_started only on first appearance."""
        snapshot = _snapshot_for(_FakeSession("alpha", False))
        events = _build_transition_events({}, snapshot, "2026-01-27T12:00:00Z")

        assert [event.type for event in events] == ["worker_started"]
        assert _build_transition_events(snapshot, snapshot, "2026-01-27T12:00:10Z") == []

    def test_idle_transition_emits_worker_idle(self) -> None:
        """Active -> idle transition should emit worker_idle."""
        previous = _snapshot_for(_FakeSession("alpha", False))
        current = _snapshot_for(_FakeSession("alpha", True))
        events = _build_transition_events(previous, current, "2026-01-27T12:01:00Z")

        # Verify the emitted event and payload details.
        assert len(events) == 1
        event = events[0]
        assert event.type == "worker_idle"
        assert event.data["previous_state"] == "active"
        assert event.data["state"] == "idle"

    def test_active_transition_emits_worker_active(self) -> None:
        """Idle -> active transition should emit worker_active."""
        previous = _snapshot_for(_FakeSession("alpha", True))
        current = _snapshot_for(_FakeSession("alpha", False))
        events = _build_transition_events(previous, current, "2026-01-27T12:02:00Z")

        # Verify the emitted event and payload details.
        assert len(events) == 1
        event = events[0]
        assert event.type == "worker_active"
        assert event.data["previous_state"] == "idle"
        assert event.data["state"] == "active"

    def test_removed_worker_emits_closed(self) -> None:
        """Removed worker should emit worker_closed with previous state."""
        previous = _snapshot_for(_FakeSession("alpha", True))
        events = _build_transition_events(previous, {}, "2026-01-27T12:03:00Z")

        # Verify the emitted event and payload details.
        assert len(events) == 1
        event = events[0]
        assert event.type == "worker_closed"
        assert event.data["previous_state"] == "idle"
        assert event.data["state"] == "closed"
