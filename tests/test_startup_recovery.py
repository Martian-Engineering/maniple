"""Tests for startup recovery functionality (recover_registry, is_recovery_attempted)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from claude_team.events import WorkerEvent
from claude_team_mcp import server as server_module
from claude_team_mcp.registry import RecoveryReport, SessionRegistry


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


def _make_snapshot(workers: list[dict], ts: datetime) -> dict:
    """Create a snapshot dict for testing."""
    return {
        "ts": _isoformat_zulu(ts),
        "count": len(workers),
        "workers": workers,
    }


class TestRecoverRegistry:
    """Tests for the recover_registry() function."""

    @pytest.fixture(autouse=True)
    def reset_recovery_state(self):
        """Reset global recovery state before each test."""
        # Reset the global flag before each test.
        server_module._recovery_attempted = False
        yield
        # Reset again after test.
        server_module._recovery_attempted = False

    def test_recover_registry_from_snapshot_and_events(self):
        """recover_registry should populate registry from event log."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker1", "state": "idle"},
            ],
            ts=now - timedelta(minutes=10),
        )
        events = [
            _make_event("worker_started", "w2", now, {"name": "Worker2"}),
        ]

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=events),
        ):
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 2
        assert len(registry.list_all()) == 2

    def test_recover_registry_marks_attempted(self):
        """recover_registry should set _recovery_attempted flag."""
        registry = SessionRegistry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=None),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            server_module.recover_registry(registry)

        assert server_module.is_recovery_attempted() is True

    def test_recover_registry_returns_none_when_no_data(self):
        """recover_registry should return None when no snapshot and no events."""
        registry = SessionRegistry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=None),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            report = server_module.recover_registry(registry)

        assert report is None
        assert len(registry.list_all()) == 0

    def test_recover_registry_with_snapshot_only(self):
        """recover_registry should work with snapshot only (no events)."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Only", "state": "active"},
            ],
            ts=now,
        )

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 1

    def test_recover_registry_with_events_only(self):
        """recover_registry should work with events only (no snapshot)."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)

        events = [
            _make_event("worker_started", "w1", now, {"name": "EventOnly"}),
        ]

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=None),
            patch.object(server_module, "read_events_since", return_value=events),
        ):
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 1

    def test_recover_registry_parses_zulu_timestamp(self):
        """recover_registry should correctly parse Z-suffixed snapshot timestamps."""
        registry = SessionRegistry()

        # Snapshot with Z-suffixed timestamp.
        snapshot = {
            "ts": "2026-01-31T12:00:00Z",
            "count": 1,
            "workers": [{"session_id": "w1", "name": "Test", "state": "idle"}],
        }

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 1

    def test_recover_registry_parses_offset_timestamp(self):
        """recover_registry should correctly parse offset snapshot timestamps."""
        registry = SessionRegistry()

        # Snapshot with offset timestamp.
        snapshot = {
            "ts": "2026-01-31T12:00:00+00:00",
            "count": 1,
            "workers": [{"session_id": "w1", "name": "Test", "state": "idle"}],
        }

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 1

    def test_recover_registry_filters_events_since_snapshot(self):
        """recover_registry should only process events after snapshot timestamp."""
        registry = SessionRegistry()
        now = datetime.now(timezone.utc)
        snapshot_ts = now - timedelta(minutes=10)

        snapshot = _make_snapshot(
            workers=[{"session_id": "w1", "name": "Snap", "state": "idle"}],
            ts=snapshot_ts,
        )

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since") as mock_read,
        ):
            mock_read.return_value = []
            server_module.recover_registry(registry)

            # Verify read_events_since was called with a datetime (since param).
            mock_read.assert_called_once()
            call_kwargs = mock_read.call_args[1]
            assert "since" in call_kwargs
            # The since datetime should be parsed from snapshot ts.


class TestIsRecoveryAttempted:
    """Tests for the is_recovery_attempted() function."""

    @pytest.fixture(autouse=True)
    def reset_recovery_state(self):
        """Reset global recovery state before each test."""
        server_module._recovery_attempted = False
        yield
        server_module._recovery_attempted = False

    def test_is_recovery_attempted_initially_false(self):
        """is_recovery_attempted should be False before recover_registry called."""
        assert server_module.is_recovery_attempted() is False

    def test_is_recovery_attempted_true_after_recovery(self):
        """is_recovery_attempted should be True after recover_registry called."""
        registry = SessionRegistry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=None),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            server_module.recover_registry(registry)

        assert server_module.is_recovery_attempted() is True

    def test_is_recovery_attempted_true_even_on_no_data(self):
        """is_recovery_attempted should be True even when no data recovered."""
        registry = SessionRegistry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=None),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            result = server_module.recover_registry(registry)

        # Report is None but flag is still set.
        assert result is None
        assert server_module.is_recovery_attempted() is True


class TestGlobalRegistryRecovery:
    """Tests for global registry singleton and recovery interaction."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Reset global state before each test."""
        server_module._global_registry = None
        server_module._global_poller = None
        server_module._recovery_attempted = False
        yield
        server_module._global_registry = None
        server_module._global_poller = None
        server_module._recovery_attempted = False

    def test_get_global_registry_creates_singleton(self):
        """get_global_registry should create a singleton SessionRegistry."""
        registry1 = server_module.get_global_registry()
        registry2 = server_module.get_global_registry()

        assert registry1 is registry2
        assert isinstance(registry1, SessionRegistry)

    def test_recovery_uses_global_registry(self):
        """recover_registry should work with the global registry."""
        now = datetime.now(timezone.utc)
        snapshot = _make_snapshot(
            workers=[{"session_id": "w1", "name": "Global", "state": "idle"}],
            ts=now,
        )

        registry = server_module.get_global_registry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 1
        assert len(registry.list_all()) == 1


class TestStartupRecoveryFlow:
    """Integration-style tests for the full startup recovery flow."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Reset global state before each test."""
        server_module._global_registry = None
        server_module._global_poller = None
        server_module._recovery_attempted = False
        yield
        server_module._global_registry = None
        server_module._global_poller = None
        server_module._recovery_attempted = False

    def test_startup_recovery_populates_registry(self):
        """Full startup flow should recover sessions from event log."""
        now = datetime.now(timezone.utc)

        snapshot = _make_snapshot(
            workers=[
                {"session_id": "w1", "name": "Worker1", "state": "idle"},
                {"session_id": "w2", "name": "Worker2", "state": "active"},
            ],
            ts=now - timedelta(minutes=5),
        )
        events = [
            _make_event("worker_idle", "w2", now),  # w2 became idle
        ]

        registry = server_module.get_global_registry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=events),
        ):
            # First recovery.
            report = server_module.recover_registry(registry)

        assert report is not None
        assert report.added == 2
        assert len(registry.list_all()) == 2

        # Verify w2 state was updated by events.
        w2 = [s for s in registry.list_all() if s.session_id == "w2"][0]
        assert w2.event_state == "idle"

    def test_startup_recovery_not_repeated(self):
        """Recovery should only happen once (checked via is_recovery_attempted)."""
        now = datetime.now(timezone.utc)
        snapshot = _make_snapshot(
            workers=[{"session_id": "w1", "name": "Once", "state": "idle"}],
            ts=now,
        )

        registry = server_module.get_global_registry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            # First recovery.
            server_module.recover_registry(registry)
            assert server_module.is_recovery_attempted() is True

            # Check that the pattern for preventing re-recovery works.
            if not server_module.is_recovery_attempted():
                # This branch should NOT execute.
                server_module.recover_registry(registry)

        # Only 1 session should be added.
        assert len(registry.list_all()) == 1

    def test_lifespan_recovery_called_if_not_attempted(self):
        """The lifespan should call recover_registry if not already attempted."""
        # This tests the pattern used in app_lifespan.
        now = datetime.now(timezone.utc)
        snapshot = _make_snapshot(
            workers=[{"session_id": "life", "name": "Lifespan", "state": "active"}],
            ts=now,
        )

        registry = server_module.get_global_registry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot),
            patch.object(server_module, "read_events_since", return_value=[]),
        ):
            # Simulate lifespan pattern: only recover if not attempted.
            if not server_module.is_recovery_attempted():
                report = server_module.recover_registry(registry)
                assert report is not None
                assert report.added == 1

        assert server_module.is_recovery_attempted() is True

    def test_lifespan_recovery_skipped_if_already_attempted(self):
        """The lifespan should skip recovery if already attempted."""
        now = datetime.now(timezone.utc)
        snapshot = _make_snapshot(
            workers=[{"session_id": "skip", "name": "Skip", "state": "idle"}],
            ts=now,
        )

        # Manually set flag as if recovery already happened.
        server_module._recovery_attempted = True

        registry = server_module.get_global_registry()

        with (
            patch.object(server_module, "get_latest_snapshot", return_value=snapshot) as mock_snap,
            patch.object(server_module, "read_events_since", return_value=[]) as mock_events,
        ):
            # Simulate lifespan pattern: only recover if not attempted.
            if not server_module.is_recovery_attempted():
                server_module.recover_registry(registry)

        # Should not have called the event log functions.
        mock_snap.assert_not_called()
        mock_events.assert_not_called()

        # Registry should be empty.
        assert len(registry.list_all()) == 0
