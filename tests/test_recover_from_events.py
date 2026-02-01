"""Tests for SessionRegistry.recover_from_events() method."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from claude_team.events import WorkerEvent
from claude_team_mcp.registry import (
    RecoveredSession,
    RecoveryReport,
    SessionRegistry,
    SessionStatus,
    TerminalId,
)


def _isoformat_zulu(value: datetime) -> str:
    """Format datetime as ISO 8601 with Zulu suffix."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_event(
    event_type: str,
    worker_id: str | None,
    ts: datetime,
    data: dict | None = None,
) -> WorkerEvent:
    """Create a WorkerEvent for testing."""
    return WorkerEvent(
        ts=_isoformat_zulu(ts),
        type=event_type,
        worker_id=worker_id,
        data=data or {},
    )


def _make_snapshot(
    workers: list[dict],
    ts: datetime,
) -> dict:
    """Create a snapshot dict for testing."""
    return {
        "ts": _isoformat_zulu(ts),
        "count": len(workers),
        "workers": workers,
    }


class TestRecoverFromEventsSnapshotOnly:
    """Tests for recovery from snapshot without events."""

    def test_recovery_from_snapshot_only_creates_sessions(self):
        """Should create RecoveredSession entries from snapshot workers."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {
                    "session_id": "worker1",
                    "name": "Groucho",
                    "project_path": "/path/to/project1",
                    "state": "idle",
                    "agent_type": "claude",
                    "terminal_id": "iterm:ABC-123",
                },
                {
                    "session_id": "worker2",
                    "name": "Harpo",
                    "project_path": "/path/to/project2",
                    "state": "active",
                    "agent_type": "claude",
                },
            ],
            ts=now,
        )

        report = registry.recover_from_events(snapshot, events=[])

        assert report.added == 2
        assert report.skipped == 0
        assert report.closed == 0

        # Verify recovered sessions are accessible via list_all.
        all_sessions = registry.list_all()
        assert len(all_sessions) == 2

    def test_recovery_preserves_worker_metadata(self):
        """Should preserve worker metadata like name, project_path, agent_type."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {
                    "session_id": "abc123",
                    "name": "Groucho",
                    "project_path": "/my/project",
                    "state": "idle",
                    "agent_type": "codex",
                    "terminal_id": "tmux:%1",
                    "claude_session_id": "uuid-123",
                    "coordinator_annotation": "Working on auth",
                    "worktree_path": "/worktree/path",
                    "main_repo_path": "/main/repo",
                },
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert len(sessions) == 1
        session = sessions[0]

        assert isinstance(session, RecoveredSession)
        assert session.name == "Groucho"
        assert session.project_path == "/my/project"
        assert session.agent_type == "codex"
        assert session.terminal_id == TerminalId("tmux", "%1")
        assert session.claude_session_id == "uuid-123"
        assert session.coordinator_annotation == "Working on auth"
        assert session.worktree_path == "/worktree/path"
        assert session.main_repo_path == "/main/repo"

    def test_snapshot_idle_state_maps_to_ready(self):
        """Idle workers in snapshot should have status READY."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker", "state": "idle"},
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert sessions[0].status == SessionStatus.READY
        assert sessions[0].event_state == "idle"

    def test_snapshot_active_state_maps_to_busy(self):
        """Active workers in snapshot should have status BUSY."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker", "state": "active"},
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert sessions[0].status == SessionStatus.BUSY
        assert sessions[0].event_state == "active"


class TestRecoverFromEventsWithEvents:
    """Tests for recovery from snapshot + events."""

    def test_events_update_state_from_snapshot(self):
        """Events after snapshot should update worker state."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Snapshot shows worker as active.
        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker", "state": "active"},
            ],
            ts=now - timedelta(minutes=5),
        )

        # Event marks worker as idle.
        events = [
            _make_event("worker_idle", "w1", now),
        ]

        registry.recover_from_events(snapshot, events)

        sessions = registry.list_all()
        assert sessions[0].event_state == "idle"
        assert sessions[0].status == SessionStatus.READY

    def test_events_add_new_workers(self):
        """Worker started events should add new workers not in snapshot."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Empty snapshot.
        snapshot = _make_snapshot(workers=[], ts=now - timedelta(minutes=5))

        # Event starts a new worker.
        events = [
            _make_event(
                "worker_started",
                "w1",
                now,
                {
                    "name": "NewWorker",
                    "project_path": "/some/path",
                },
            ),
        ]

        report = registry.recover_from_events(snapshot, events)

        assert report.added == 1
        sessions = registry.list_all()
        assert len(sessions) == 1
        assert sessions[0].name == "NewWorker"
        assert sessions[0].event_state == "active"

    def test_events_only_no_snapshot(self):
        """Recovery should work with None snapshot and only events."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        events = [
            _make_event(
                "worker_started",
                "w1",
                now,
                {"name": "Solo", "project_path": "/path"},
            ),
            _make_event("worker_idle", "w1", now + timedelta(seconds=30)),
        ]

        report = registry.recover_from_events(None, events)

        assert report.added == 1
        sessions = registry.list_all()
        assert sessions[0].event_state == "idle"

    def test_snapshot_events_in_events_list(self):
        """Should process embedded snapshot events in events list."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        events = [
            _make_event(
                "snapshot",
                None,
                now,
                {
                    "count": 2,
                    "workers": [
                        {"session_id": "w1", "name": "One", "state": "idle"},
                        {"session_id": "w2", "name": "Two", "state": "active"},
                    ],
                },
            ),
        ]

        report = registry.recover_from_events(None, events)

        assert report.added == 2
        sessions = registry.list_all()
        assert len(sessions) == 2

    def test_last_event_ts_tracks_most_recent_event(self):
        """last_event_ts should reflect the most recent event for worker."""
        registry = SessionRegistry()
        base = datetime.now(timezone.utc) - timedelta(hours=1)

        snapshot = _make_snapshot(
            workers=[{"session_id": "w1", "name": "Worker", "state": "active"}],
            ts=base,
        )

        later = base + timedelta(minutes=30)
        events = [
            _make_event("worker_idle", "w1", later),
        ]

        registry.recover_from_events(snapshot, events)

        sessions = registry.list_all()
        # last_event_ts should be the idle event timestamp (later than snapshot).
        assert sessions[0].last_event_ts > base  # Updated from snapshot
        # Since there was an event after snapshot, last_event_ts > snapshot_ts.
        assert sessions[0].last_event_ts.hour == later.hour
        assert sessions[0].last_event_ts.minute == later.minute


class TestRecoverFromEventsLiveSessionsNotOverwritten:
    """Tests ensuring live sessions are not overwritten by recovery."""

    def test_live_sessions_not_overwritten(self):
        """Existing live sessions in registry should not be overwritten."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Add a live session first.
        mock_terminal = MagicMock()
        mock_terminal.backend_id = "iterm"
        mock_terminal.native_id = "LIVE-UUID"
        live_session = registry.add(
            mock_terminal,
            "/live/project",
            name="LiveWorker",
            session_id="w1",
        )

        # Snapshot tries to add same session_id.
        snapshot = _make_snapshot(
            workers=[
                {
                    "session_id": "w1",
                    "name": "SnapshotWorker",
                    "project_path": "/snapshot/project",
                    "state": "idle",
                },
            ],
            ts=now,
        )

        report = registry.recover_from_events(snapshot, events=[])

        # Should skip, not add.
        assert report.added == 0
        assert report.skipped == 1
        assert report.closed == 0

        # Original live session should be unchanged.
        sessions = registry.list_all()
        assert len(sessions) == 1
        assert sessions[0].name == "LiveWorker"
        assert sessions[0].project_path == "/live/project"

    def test_recovery_idempotent(self):
        """Calling recover_from_events twice should not duplicate sessions."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker", "state": "idle"},
            ],
            ts=now,
        )

        # First recovery.
        report1 = registry.recover_from_events(snapshot, events=[])
        assert report1.added == 1

        # Second recovery with same data.
        report2 = registry.recover_from_events(snapshot, events=[])
        assert report2.added == 0
        assert report2.skipped == 1

        # Should still only have one session.
        assert len(registry.list_all()) == 1


class TestRecoverFromEventsClosedSessions:
    """Tests for closed session handling during recovery."""

    def test_closed_sessions_tracked_in_report(self):
        """Closed workers should be counted in RecoveryReport.closed."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Closed", "state": "closed"},
                {"session_id": "w2", "name": "Active", "state": "active"},
            ],
            ts=now,
        )

        report = registry.recover_from_events(snapshot, events=[])

        assert report.added == 2
        assert report.closed == 1

    def test_closed_state_from_event(self):
        """worker_closed event should mark session as closed."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        events = [
            _make_event(
                "worker_started",
                "w1",
                now - timedelta(minutes=10),
                {"name": "Worker", "project_path": "/path"},
            ),
            _make_event("worker_closed", "w1", now),
        ]

        report = registry.recover_from_events(None, events)

        assert report.added == 1
        assert report.closed == 1

        sessions = registry.list_all()
        assert sessions[0].event_state == "closed"
        assert sessions[0].status == SessionStatus.BUSY

    def test_closed_maps_to_busy_status(self):
        """Closed workers should have status BUSY (last known working state)."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Closed", "state": "closed"},
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert sessions[0].status == SessionStatus.BUSY
        assert sessions[0].is_idle() is False


class TestRecoverFromEventsEmptyInput:
    """Tests for empty/null input handling."""

    def test_empty_snapshot_no_events(self):
        """Empty snapshot with no events should return empty recovery."""
        registry = SessionRegistry()

        snapshot = _make_snapshot(workers=[], ts=datetime.now(timezone.utc))
        report = registry.recover_from_events(snapshot, events=[])

        assert report.added == 0
        assert report.skipped == 0
        assert report.closed == 0
        assert len(registry.list_all()) == 0

    def test_none_snapshot_no_events(self):
        """None snapshot with no events should return empty recovery."""
        registry = SessionRegistry()

        report = registry.recover_from_events(None, events=[])

        assert report.added == 0
        assert report.skipped == 0
        assert report.closed == 0
        assert len(registry.list_all()) == 0

    def test_none_snapshot_with_events(self):
        """None snapshot with events should still process events."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        events = [
            _make_event("worker_started", "w1", now, {"name": "W1"}),
        ]

        report = registry.recover_from_events(None, events)

        assert report.added == 1
        assert len(registry.list_all()) == 1


class TestRecoveryReportAccuracy:
    """Tests for RecoveryReport count accuracy."""

    def test_report_counts_are_accurate(self):
        """RecoveryReport should have accurate counts for all categories."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Add a live session that will cause a skip.
        mock_terminal = MagicMock()
        mock_terminal.backend_id = "iterm"
        mock_terminal.native_id = "LIVE-UUID"
        registry.add(mock_terminal, "/live/path", session_id="w1")

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Skip", "state": "idle"},  # Will skip
                {"session_id": "w2", "name": "Add", "state": "active"},  # Will add
                {"session_id": "w3", "name": "Closed", "state": "closed"},  # Will add + closed
            ],
            ts=now,
        )

        report = registry.recover_from_events(snapshot, events=[])

        assert report.added == 2
        assert report.skipped == 1
        assert report.closed == 1
        assert report.timestamp is not None

    def test_report_timestamp_is_utc(self):
        """RecoveryReport timestamp should be timezone-aware UTC."""
        registry = SessionRegistry()

        report = registry.recover_from_events(None, [])

        assert report.timestamp is not None
        assert report.timestamp.tzinfo is not None


class TestRecoverFromEventsEdgeCases:
    """Edge case tests for recovery."""

    def test_malformed_worker_in_snapshot_skipped(self):
        """Workers without session_id should be skipped gracefully."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = {
            "ts": _isoformat_zulu(now),
            "count": 2,
            "workers": [
                {"name": "NoId"},  # Missing session_id
                {"session_id": "w1", "name": "Valid", "state": "idle"},
            ],
        }

        report = registry.recover_from_events(snapshot, events=[])

        # Only the valid worker should be added.
        assert report.added == 1
        assert len(registry.list_all()) == 1

    def test_unknown_state_defaults_to_active(self):
        """Unknown state values should default to 'active'."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker", "state": "unknown_state"},
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert sessions[0].event_state == "active"
        assert sessions[0].status == SessionStatus.BUSY

    def test_missing_state_defaults_to_active(self):
        """Missing state field should default to 'active'."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker"},  # No state field
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert sessions[0].event_state == "active"

    def test_invalid_agent_type_defaults_to_claude(self):
        """Invalid agent_type should default to 'claude'."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker", "agent_type": "invalid"},
            ],
            ts=now,
        )

        registry.recover_from_events(snapshot, events=[])

        sessions = registry.list_all()
        assert sessions[0].agent_type == "claude"

    def test_worker_id_extraction_fallbacks(self):
        """Should extract worker_id from session_id, worker_id, or id fields."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Test each possible ID field name.
        for id_field in ["session_id", "worker_id", "id"]:
            reg = SessionRegistry()
            snapshot = {
                "ts": _isoformat_zulu(now),
                "count": 1,
                "workers": [{id_field: f"worker_{id_field}", "name": "Test"}],
            }

            report = reg.recover_from_events(snapshot, events=[])
            assert report.added == 1
            sessions = reg.list_all()
            assert sessions[0].session_id == f"worker_{id_field}"

    def test_zulu_timestamp_parsed_correctly(self):
        """Z-suffixed timestamps should be parsed as UTC."""
        registry = SessionRegistry()

        snapshot = {
            "ts": "2026-01-31T12:00:00Z",
            "count": 1,
            "workers": [{"session_id": "w1", "name": "Test", "state": "idle"}],
        }

        report = registry.recover_from_events(snapshot, events=[])

        assert report.added == 1

    def test_offset_timestamp_parsed_correctly(self):
        """Offset timestamps should be parsed correctly."""
        registry = SessionRegistry()

        snapshot = {
            "ts": "2026-01-31T12:00:00+00:00",
            "count": 1,
            "workers": [{"session_id": "w1", "name": "Test", "state": "idle"}],
        }

        report = registry.recover_from_events(snapshot, events=[])

        assert report.added == 1


class TestRecoverFromEventsListMethods:
    """Tests for registry list methods with recovered sessions."""

    def test_list_all_includes_recovered_sessions(self):
        """list_all should include both live and recovered sessions."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Add live session.
        mock_terminal = MagicMock()
        mock_terminal.backend_id = "iterm"
        mock_terminal.native_id = "LIVE"
        registry.add(mock_terminal, "/live", name="Live", session_id="live1")

        # Recover session.
        snapshot = _make_snapshot(
            workers=[{"session_id": "recovered1", "name": "Recovered", "state": "idle"}],
            ts=now,
        )
        registry.recover_from_events(snapshot, events=[])

        all_sessions = registry.list_all()
        assert len(all_sessions) == 2
        names = {s.name for s in all_sessions}
        assert names == {"Live", "Recovered"}

    def test_list_by_status_includes_recovered_sessions(self):
        """list_by_status should filter both live and recovered sessions."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Add live session with READY status.
        mock_terminal = MagicMock()
        mock_terminal.backend_id = "iterm"
        mock_terminal.native_id = "LIVE"
        live = registry.add(mock_terminal, "/live", name="Live", session_id="live1")
        live.status = SessionStatus.READY

        # Recover one READY (idle) and one BUSY (active) session.
        snapshot = _make_snapshot(
            workers=[
                {"session_id": "r1", "name": "Idle", "state": "idle"},
                {"session_id": "r2", "name": "Active", "state": "active"},
            ],
            ts=now,
        )
        registry.recover_from_events(snapshot, events=[])

        ready_sessions = registry.list_by_status(SessionStatus.READY)
        busy_sessions = registry.list_by_status(SessionStatus.BUSY)

        assert len(ready_sessions) == 2  # Live + Idle
        assert len(busy_sessions) == 1  # Active only

    def test_live_session_shadows_recovered(self):
        """Live session with same ID should shadow recovered session in list."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        # Add live session with ID "shared".
        mock_terminal = MagicMock()
        mock_terminal.backend_id = "iterm"
        mock_terminal.native_id = "LIVE"
        registry.add(mock_terminal, "/live", name="LiveShared", session_id="shared")

        # Recover session with same ID.
        snapshot = _make_snapshot(
            workers=[{"session_id": "shared", "name": "RecoveredShared", "state": "idle"}],
            ts=now,
        )
        registry.recover_from_events(snapshot, events=[])

        all_sessions = registry.list_all()
        assert len(all_sessions) == 1
        assert all_sessions[0].name == "LiveShared"  # Live takes precedence
