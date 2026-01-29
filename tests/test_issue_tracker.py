"""
Tests for issue tracker abstraction module.
"""

import os

import pytest

from claude_team_mcp.config import IssueTrackerConfig, default_config
from claude_team_mcp.issue_tracker import (
    BEADS_BACKEND,
    ISSUE_TRACKER_ENV_VAR,
    PEBBLES_BACKEND,
    IssueTrackerBackend,
    detect_issue_tracker,
)


class TestIssueTrackerBackendProtocol:
    """Tests for IssueTrackerBackend protocol compliance."""

    def test_beads_backend_is_protocol(self):
        """Beads backend should satisfy IssueTrackerBackend protocol."""
        assert isinstance(BEADS_BACKEND, IssueTrackerBackend)

    def test_pebbles_backend_is_protocol(self):
        """Pebbles backend should satisfy IssueTrackerBackend protocol."""
        assert isinstance(PEBBLES_BACKEND, IssueTrackerBackend)


class TestBackendCommands:
    """Tests for backend command templates."""

    def test_beads_commands_include_expected_keys(self):
        """Beads commands should include all required templates."""
        expected_keys = {
            "list",
            "ready",
            "show",
            "update",
            "close",
            "create",
            "comment",
            "dep_add",
            "dep_tree",
        }
        assert set(BEADS_BACKEND.commands.keys()) == expected_keys

    def test_pebbles_commands_include_expected_keys(self):
        """Pebbles commands should include all required templates."""
        expected_keys = {
            "list",
            "ready",
            "show",
            "update",
            "close",
            "create",
            "comment",
            "dep_add",
            "dep_tree",
        }
        assert set(PEBBLES_BACKEND.commands.keys()) == expected_keys

    def test_beads_commands_start_with_cli(self):
        """Beads commands should start with the beads CLI prefix."""
        for command in BEADS_BACKEND.commands.values():
            assert command.startswith("bd --no-db")

    def test_pebbles_commands_start_with_cli(self):
        """Pebbles commands should start with the pebbles CLI prefix."""
        for command in PEBBLES_BACKEND.commands.values():
            assert command.startswith("pb ")


class TestDetectIssueTracker:
    """Tests for issue tracker detection."""

    def test_detects_beads(self, tmp_path):
        """Detection should return beads backend when .beads exists."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected == BEADS_BACKEND

    def test_detects_pebbles(self, tmp_path):
        """Detection should return pebbles backend when .pebbles exists."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected == PEBBLES_BACKEND

    def test_detects_pebbles_when_both_markers_present(self, tmp_path, caplog):
        """Detection should prefer pebbles when both markers are present."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()
        (project_path / ".pebbles").mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected == PEBBLES_BACKEND
        assert "defaulting to pebbles" in caplog.text

    def test_returns_none_when_no_marker(self, tmp_path):
        """Detection should return None when no tracker marker exists."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        detected = detect_issue_tracker(str(project_path))
        assert detected is None


class TestEnvVarOverride:
    """Tests for CLAUDE_TEAM_ISSUE_TRACKER environment variable override."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        """Ensure the env var is cleared before each test."""
        monkeypatch.delenv(ISSUE_TRACKER_ENV_VAR, raising=False)

    def test_env_var_selects_beads(self, tmp_path, monkeypatch):
        """Env var should select beads even with no markers."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        monkeypatch.setenv(ISSUE_TRACKER_ENV_VAR, "beads")

        detected = detect_issue_tracker(str(project_path))
        assert detected == BEADS_BACKEND

    def test_env_var_selects_pebbles(self, tmp_path, monkeypatch):
        """Env var should select pebbles even with no markers."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        monkeypatch.setenv(ISSUE_TRACKER_ENV_VAR, "pebbles")

        detected = detect_issue_tracker(str(project_path))
        assert detected == PEBBLES_BACKEND

    def test_env_var_overrides_markers(self, tmp_path, monkeypatch):
        """Env var should take priority over marker detection."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()  # Pebbles marker
        monkeypatch.setenv(ISSUE_TRACKER_ENV_VAR, "beads")

        detected = detect_issue_tracker(str(project_path))
        assert detected == BEADS_BACKEND

    def test_env_var_case_insensitive(self, tmp_path, monkeypatch):
        """Env var should be case-insensitive."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        monkeypatch.setenv(ISSUE_TRACKER_ENV_VAR, "BEADS")

        detected = detect_issue_tracker(str(project_path))
        assert detected == BEADS_BACKEND

    def test_invalid_env_var_falls_through(self, tmp_path, monkeypatch, caplog):
        """Invalid env var value should log warning and fall through."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()
        monkeypatch.setenv(ISSUE_TRACKER_ENV_VAR, "invalid_tracker")

        detected = detect_issue_tracker(str(project_path))
        assert detected == PEBBLES_BACKEND
        assert "Unknown issue tracker 'invalid_tracker'" in caplog.text


class TestConfigOverride:
    """Tests for config.issue_tracker.override setting."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        """Ensure the env var is cleared before each test."""
        monkeypatch.delenv(ISSUE_TRACKER_ENV_VAR, raising=False)

    def test_config_override_selects_beads(self, tmp_path):
        """Config override should select beads even with no markers."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        config = default_config()
        config.issue_tracker = IssueTrackerConfig(override="beads")

        detected = detect_issue_tracker(str(project_path), config=config)
        assert detected == BEADS_BACKEND

    def test_config_override_selects_pebbles(self, tmp_path):
        """Config override should select pebbles even with no markers."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        config = default_config()
        config.issue_tracker = IssueTrackerConfig(override="pebbles")

        detected = detect_issue_tracker(str(project_path), config=config)
        assert detected == PEBBLES_BACKEND

    def test_config_override_overrides_markers(self, tmp_path):
        """Config override should take priority over marker detection."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".pebbles").mkdir()  # Pebbles marker
        config = default_config()
        config.issue_tracker = IssueTrackerConfig(override="beads")

        detected = detect_issue_tracker(str(project_path), config=config)
        assert detected == BEADS_BACKEND

    def test_env_var_overrides_config(self, tmp_path, monkeypatch):
        """Env var should take priority over config override."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        config = default_config()
        config.issue_tracker = IssueTrackerConfig(override="pebbles")
        monkeypatch.setenv(ISSUE_TRACKER_ENV_VAR, "beads")

        detected = detect_issue_tracker(str(project_path), config=config)
        assert detected == BEADS_BACKEND

    def test_none_override_falls_through_to_markers(self, tmp_path):
        """None config override should fall through to marker detection."""
        project_path = tmp_path / "repo"
        project_path.mkdir()
        (project_path / ".beads").mkdir()
        config = default_config()
        config.issue_tracker = IssueTrackerConfig(override=None)

        detected = detect_issue_tracker(str(project_path), config=config)
        assert detected == BEADS_BACKEND
