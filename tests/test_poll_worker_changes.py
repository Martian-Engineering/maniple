"""Tests for poll_worker_changes config integration."""

import json
from pathlib import Path

import pytest

from claude_team_mcp import config as config_module
from claude_team_mcp.config import EventsConfig, load_config


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
