"""Tests for worker_events MCP tool."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from claude_team.events import WorkerEvent
from claude_team_mcp.tools import worker_events as worker_events_module


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


class TestParseIsoTimestamp:
    """Tests for _parse_iso_timestamp helper."""

    def test_parses_zulu_format(self):
        """Should parse Z-suffixed timestamps."""
        result = worker_events_module._parse_iso_timestamp("2026-01-27T11:40:00Z")
        assert result is not None
        assert result.tzinfo == timezone.utc
        assert result.hour == 11

    def test_parses_offset_format(self):
        """Should parse +00:00 offset timestamps."""
        result = worker_events_module._parse_iso_timestamp("2026-01-27T11:40:00+00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_returns_none_for_invalid(self):
        """Should return None for invalid timestamps."""
        assert worker_events_module._parse_iso_timestamp("not-a-timestamp") is None

    def test_returns_none_for_empty(self):
        """Should return None for empty string."""
        assert worker_events_module._parse_iso_timestamp("") is None
        assert worker_events_module._parse_iso_timestamp("  ") is None


class TestSerializeEvent:
    """Tests for _serialize_event helper."""

    def test_serializes_all_fields(self):
        """Should include ts, type, worker_id, and data."""
        event = _make_event(
            "worker_started",
            "abc123",
            datetime(2026, 1, 27, 11, 40, tzinfo=timezone.utc),
            {"name": "Groucho"},
        )
        result = worker_events_module._serialize_event(event)

        assert result["ts"] == "2026-01-27T11:40:00Z"
        assert result["type"] == "worker_started"
        assert result["worker_id"] == "abc123"
        assert result["data"] == {"name": "Groucho"}

    def test_handles_none_worker_id(self):
        """Should handle snapshot events with None worker_id."""
        event = _make_event(
            "snapshot",
            None,
            datetime(2026, 1, 27, 11, 40, tzinfo=timezone.utc),
            {"count": 2, "workers": []},
        )
        result = worker_events_module._serialize_event(event)

        assert result["worker_id"] is None


class TestFilterByProject:
    """Tests for _filter_by_project helper."""

    def test_filters_matching_project(self):
        """Should include only events matching project filter."""
        events = [
            _make_event("worker_started", "a", datetime.now(timezone.utc), {"project_path": "/foo/bar"}),
            _make_event("worker_started", "b", datetime.now(timezone.utc), {"project_path": "/baz/qux"}),
            _make_event("worker_started", "c", datetime.now(timezone.utc), {"project": "/foo/other"}),
        ]

        result = worker_events_module._filter_by_project(events, "/foo")
        worker_ids = [e.worker_id for e in result]

        assert "a" in worker_ids
        assert "c" in worker_ids
        assert "b" not in worker_ids

    def test_includes_events_without_project(self):
        """Should include events without project info (like snapshots)."""
        events = [
            _make_event("snapshot", None, datetime.now(timezone.utc), {"count": 1}),
            _make_event("worker_started", "a", datetime.now(timezone.utc), {"project_path": "/other"}),
        ]

        result = worker_events_module._filter_by_project(events, "/foo")

        # Snapshot should be included (no project), worker should not
        assert len(result) == 1
        assert result[0].type == "snapshot"


class TestBuildSummary:
    """Tests for _build_summary helper."""

    def test_tracks_started_workers(self):
        """Should list worker IDs from worker_started events."""
        events = [
            _make_event("worker_started", "a", datetime.now(timezone.utc)),
            _make_event("worker_started", "b", datetime.now(timezone.utc)),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert set(result["started"]) == {"a", "b"}

    def test_tracks_closed_workers(self):
        """Should list worker IDs from worker_closed events."""
        events = [
            _make_event("worker_closed", "a", datetime.now(timezone.utc)),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert result["closed"] == ["a"]

    def test_tracks_idle_workers(self):
        """Should list worker IDs from worker_idle events."""
        events = [
            _make_event("worker_idle", "a", datetime.now(timezone.utc)),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert result["idle"] == ["a"]

    def test_tracks_active_workers(self):
        """Should list worker IDs from worker_active events."""
        events = [
            _make_event("worker_active", "a", datetime.now(timezone.utc)),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert result["active"] == ["a"]

    def test_detects_stuck_workers(self):
        """Should mark active workers as stuck if last activity exceeds threshold."""
        # Worker became active 20 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        events = [
            _make_event("worker_started", "a", old_time),
            _make_event("worker_active", "a", old_time),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert "a" in result["stuck"]

    def test_does_not_mark_recent_active_as_stuck(self):
        """Should not mark recently active workers as stuck."""
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        events = [
            _make_event("worker_started", "a", recent_time),
            _make_event("worker_active", "a", recent_time),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert "a" not in result["stuck"]

    def test_idle_workers_not_stuck(self):
        """Should not mark idle workers as stuck."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        events = [
            _make_event("worker_started", "a", old_time),
            _make_event("worker_idle", "a", old_time),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert "a" not in result["stuck"]

    def test_closed_workers_not_stuck(self):
        """Should not mark closed workers as stuck."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        events = [
            _make_event("worker_started", "a", old_time),
            _make_event("worker_active", "a", old_time - timedelta(minutes=5)),
            _make_event("worker_closed", "a", old_time),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert "a" not in result["stuck"]

    def test_last_event_ts(self):
        """Should track the last event timestamp."""
        ts1 = datetime(2026, 1, 27, 11, 40, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 27, 11, 45, tzinfo=timezone.utc)
        events = [
            _make_event("worker_started", "a", ts1),
            _make_event("worker_idle", "a", ts2),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        assert result["last_event_ts"] == "2026-01-27T11:45:00Z"

    def test_empty_events_returns_empty_lists(self):
        """Should return empty lists for no events."""
        result = worker_events_module._build_summary([], stale_threshold_minutes=10)

        assert result["started"] == []
        assert result["closed"] == []
        assert result["idle"] == []
        assert result["active"] == []
        assert result["stuck"] == []
        assert result["last_event_ts"] is None

    def test_processes_snapshot_for_state_tracking(self):
        """Should update state tracking from snapshot events."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        events = [
            _make_event(
                "snapshot",
                None,
                old_time,
                {
                    "workers": [
                        {"session_id": "a", "state": "active"},
                        {"session_id": "b", "state": "idle"},
                    ]
                },
            ),
        ]

        result = worker_events_module._build_summary(events, stale_threshold_minutes=10)

        # Worker "a" should be stuck (active and old)
        assert "a" in result["stuck"]
        # Worker "b" should not be stuck (idle)
        assert "b" not in result["stuck"]


class TestWorkerEventsTool:
    """Integration tests for the worker_events tool function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock MCP context."""
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_empty_event_log_returns_empty_result(self, mock_context):
        """Should return empty events list when log is empty."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = []
            mock_events.get_latest_snapshot.return_value = None

            # Get the actual function from the module
            # We need to call register_tools to get access to the function
            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context)

            assert result["events"] == []
            assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_basic_since_limit_filtering(self, mock_context):
        """Should pass since and limit to read_events_since."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = [
                _make_event("worker_started", "a", datetime.now(timezone.utc)),
            ]

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(
                mock_context,
                since="2026-01-27T11:40:00Z",
                limit=500,
            )

            # Verify read_events_since was called with correct args
            mock_events.read_events_since.assert_called_once()
            call_args = mock_events.read_events_since.call_args
            assert call_args[1]["limit"] == 500
            assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_include_snapshot_flag(self, mock_context):
        """Should include snapshot when include_snapshot=True."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = []
            mock_events.get_latest_snapshot.return_value = {
                "ts": "2026-01-27T11:30:00Z",
                "count": 2,
                "workers": [{"session_id": "a"}, {"session_id": "b"}],
            }

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context, include_snapshot=True)

            assert "snapshot" in result
            assert result["snapshot"]["data"]["count"] == 2

    @pytest.mark.asyncio
    async def test_include_snapshot_false_by_default(self, mock_context):
        """Should not include snapshot by default."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = []

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context)

            assert "snapshot" not in result
            mock_events.get_latest_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_summary_flag(self, mock_context):
        """Should include summary when include_summary=True."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = [
                _make_event("worker_started", "a", datetime.now(timezone.utc)),
                _make_event("worker_idle", "a", datetime.now(timezone.utc)),
            ]

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context, include_summary=True)

            assert "summary" in result
            assert "a" in result["summary"]["started"]
            assert "a" in result["summary"]["idle"]

    @pytest.mark.asyncio
    async def test_include_summary_false_by_default(self, mock_context):
        """Should not include summary by default."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = []

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context)

            assert "summary" not in result

    @pytest.mark.asyncio
    async def test_project_filter_applied(self, mock_context):
        """Should filter events by project when project_filter is set."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = [
                _make_event("worker_started", "a", datetime.now(timezone.utc), {"project_path": "/foo/bar"}),
                _make_event("worker_started", "b", datetime.now(timezone.utc), {"project_path": "/baz/qux"}),
            ]

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context, project_filter="/foo")

            assert result["count"] == 1
            assert result["events"][0]["worker_id"] == "a"

    @pytest.mark.asyncio
    async def test_invalid_since_returns_error(self, mock_context):
        """Should return error for invalid since timestamp."""
        mcp = MagicMock()
        captured_func = None

        def capture_tool():
            def decorator(func):
                nonlocal captured_func
                captured_func = func
                return func
            return decorator

        mcp.tool = capture_tool
        worker_events_module.register_tools(mcp)

        result = await captured_func(mock_context, since="not-a-timestamp")

        assert "error" in result
        assert "Invalid since timestamp" in result["error"]

    @pytest.mark.asyncio
    async def test_summary_with_stuck_worker_detection(self, mock_context):
        """Should detect stuck workers in summary based on stale_threshold_minutes."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = [
                _make_event("worker_started", "stuck-worker", old_time),
                _make_event("worker_active", "stuck-worker", old_time),
            ]

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(
                mock_context,
                include_summary=True,
                stale_threshold_minutes=10,
            )

            assert "stuck-worker" in result["summary"]["stuck"]

    @pytest.mark.asyncio
    async def test_snapshot_none_when_no_snapshot_available(self, mock_context):
        """Should set snapshot to None when no snapshot is available."""
        with patch.object(worker_events_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = []
            mock_events.get_latest_snapshot.return_value = None

            mcp = MagicMock()
            captured_func = None

            def capture_tool():
                def decorator(func):
                    nonlocal captured_func
                    captured_func = func
                    return func
                return decorator

            mcp.tool = capture_tool
            worker_events_module.register_tools(mcp)

            result = await captured_func(mock_context, include_snapshot=True)

            assert result["snapshot"] is None
