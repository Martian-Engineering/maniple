"""Tests for poll_worker_changes config integration."""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from maniple.events import WorkerEvent
from maniple_mcp import config as config_module
from maniple_mcp.config import EventsConfig, load_config
from maniple_mcp.tools import poll_worker_changes as poll_worker_changes_module


@pytest.fixture(autouse=True)
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config path to a temp location for deterministic tests."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    return path


class TestStaleThresholdConfigDefault:
    """Tests for stale_threshold_minutes config defaults."""

    def test_default_is_10(self):
        """EventsConfig default stale_threshold_minutes is 10."""
        assert EventsConfig.stale_threshold_minutes == 10

    def test_load_config_returns_default(self, config_path: Path):
        """load_config returns default stale_threshold_minutes when not in file."""
        config = load_config()
        assert config.events.stale_threshold_minutes == 10

    def test_load_config_reads_custom_value(self, config_path: Path):
        """load_config reads stale_threshold_minutes from file."""
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"stale_threshold_minutes": 30},
        }))
        config = load_config()
        assert config.events.stale_threshold_minutes == 30

    def test_config_override_precedence(self, config_path: Path):
        """Tool param should take precedence over config value.

        This tests the intended usage pattern: when the tool receives None
        for stale_threshold_minutes, it falls back to config. When a value
        is explicitly provided, that value is used instead.
        """
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"stale_threshold_minutes": 25},
        }))
        config = load_config()

        # Simulate the tool logic: None -> config default
        tool_param = None
        effective = tool_param if tool_param is not None else config.events.stale_threshold_minutes
        assert effective == 25

        # Simulate the tool logic: explicit value -> override
        tool_param = 5
        effective = tool_param if tool_param is not None else config.events.stale_threshold_minutes
        assert effective == 5


def _make_event(event_type: str, data: dict | None = None) -> WorkerEvent:
    """Create a WorkerEvent for poll_worker_changes tests."""
    ts = datetime(2026, 1, 27, 11, 40, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return WorkerEvent(
        ts=ts,
        type=event_type,
        worker_id="worker-1",
        data=data or {},
    )


class TestIssueIdExtraction:
    """Tests for issue ID extraction compatibility."""

    def test_prefers_existing_legacy_key_order(self):
        """Extraction should keep existing key precedence behavior."""
        event = _make_event(
            "worker_closed",
            data={"bead": "legacy-bead", "issue": "legacy-issue", "issue_id": "canonical"},
        )
        assert poll_worker_changes_module._event_issue_id(event) == "legacy-bead"

    def test_returns_none_when_no_issue_keys_present(self):
        """Extraction should return None when issue keys are missing."""
        event = _make_event("worker_closed", data={"name": "Groucho"})
        assert poll_worker_changes_module._event_issue_id(event) is None


class TestPollWorkerChangesPayload:
    """Integration tests for poll_worker_changes payload fields."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock MCP context with an empty worker registry."""
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()
        ctx.request_context.lifespan_context.registry.list_all.return_value = []
        return ctx

    def _capture_tool(self):
        """Register poll_worker_changes and return the callable tool function."""
        mcp = MagicMock()
        captured_func = None

        def capture():
            def decorator(func):
                nonlocal captured_func
                captured_func = func
                return func

            return decorator

        mcp.tool = capture
        poll_worker_changes_module.register_tools(mcp)
        assert captured_func is not None
        return captured_func

    @pytest.mark.parametrize("legacy_key", ["bead", "issue", "issue_id"])
    @pytest.mark.asyncio
    async def test_completed_summary_emits_issue_id_field(self, mock_context, legacy_key: str):
        """Completed summary should emit issue_id for all supported input keys."""
        with patch.object(poll_worker_changes_module, "events_module") as mock_events:
            mock_events.read_events_since.return_value = [
                _make_event("worker_closed", data={"name": "Groucho", legacy_key: "cic-123"}),
            ]

            tool_func = self._capture_tool()
            result = await tool_func(mock_context, stale_threshold_minutes=10)

            completed = result["summary"]["completed"]
            assert len(completed) == 1
            assert completed[0]["name"] == "Groucho"
            assert completed[0]["issue_id"] == "cic-123"
            assert completed[0]["duration_min"] == 0
            assert "bead" not in completed[0]
