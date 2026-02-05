"""Tests for Codex worker JSONL path resolution (cic-e24).

Validates that:
1. get_jsonl_path() returns None (not wrong file) when Codex marker discovery fails
2. get_jsonl_path() uses cached codex_jsonl_path when available
3. is_idle() uses get_jsonl_path() without blind fallback
4. codex_jsonl_path is persisted in to_dict() for event log recovery
5. RecoveredSession includes codex_jsonl_path from event data
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_team_mcp.registry import (
    ManagedSession,
    RecoveredSession,
    SessionStatus,
    TerminalId,
)


class TestCodexGetJsonlPathNoBlindFallback:
    """get_jsonl_path() must not return wrong session data for Codex workers."""

    def _make_codex_session(self, session_id="test-abc1", codex_jsonl_path=None):
        """Create a ManagedSession configured as a Codex worker."""
        mock_terminal = MagicMock()
        session = ManagedSession(
            session_id=session_id,
            terminal_session=mock_terminal,
            project_path="/test/project",
            agent_type="codex",
        )
        if codex_jsonl_path:
            session.codex_jsonl_path = codex_jsonl_path
        return session

    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_returns_none_when_discovery_fails(self, mock_find):
        """get_jsonl_path returns None when marker discovery fails, not a random file."""
        mock_find.return_value = None
        session = self._make_codex_session()

        result = session.get_jsonl_path()

        assert result is None
        # Verify it used generous max_age
        mock_find.assert_called_once_with("test-abc1", max_age_seconds=86400)

    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_uses_cached_path_when_available(self, mock_find):
        """get_jsonl_path returns cached codex_jsonl_path without re-discovery."""
        cached_path = Path("/tmp/test-codex-session.jsonl")
        cached_path.touch()

        try:
            session = self._make_codex_session(codex_jsonl_path=cached_path)

            result = session.get_jsonl_path()

            assert result == cached_path
            # Should NOT call find_codex_session_by_internal_id when cache is valid
            mock_find.assert_not_called()
        finally:
            cached_path.unlink(missing_ok=True)

    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_falls_through_when_cached_path_missing(self, mock_find):
        """get_jsonl_path tries re-discovery when cached file no longer exists."""
        mock_find.return_value = None
        nonexistent_path = Path("/tmp/nonexistent-codex-session.jsonl")
        session = self._make_codex_session(codex_jsonl_path=nonexistent_path)

        result = session.get_jsonl_path()

        assert result is None
        # Should try marker-based discovery when cached path doesn't exist
        mock_find.assert_called_once()

    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_caches_path_on_successful_discovery(self, mock_find):
        """get_jsonl_path caches the path when marker discovery succeeds."""
        mock_match = MagicMock()
        mock_match.jsonl_path = Path("/tmp/discovered-codex.jsonl")
        mock_find.return_value = mock_match

        session = self._make_codex_session()

        result = session.get_jsonl_path()

        assert result == Path("/tmp/discovered-codex.jsonl")
        assert session.codex_jsonl_path == Path("/tmp/discovered-codex.jsonl")

    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_uses_86400_max_age_for_rediscovery(self, mock_find):
        """get_jsonl_path uses 24h max_age (not 600s) for marker discovery."""
        mock_find.return_value = None
        session = self._make_codex_session()

        session.get_jsonl_path()

        mock_find.assert_called_once_with("test-abc1", max_age_seconds=86400)


class TestCodexIsIdleNoBlindFallback:
    """is_idle() for Codex workers must not use blind fallback."""

    def _make_codex_session(self, session_id="test-abc1"):
        """Create a ManagedSession configured as a Codex worker."""
        mock_terminal = MagicMock()
        return ManagedSession(
            session_id=session_id,
            terminal_session=mock_terminal,
            project_path="/test/project",
            agent_type="codex",
        )

    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_returns_false_when_no_session_file(self, mock_find):
        """is_idle returns False (not True from wrong file) when discovery fails."""
        mock_find.return_value = None
        session = self._make_codex_session()

        result = session.is_idle()

        assert result is False

    @patch("claude_team_mcp.idle_detection.is_codex_idle")
    @patch("claude_team_mcp.registry.find_codex_session_by_internal_id")
    def test_uses_correct_session_file(self, mock_find, mock_is_idle):
        """is_idle uses the cached/discovered path, not a random recent file."""
        mock_find.return_value = None
        session = self._make_codex_session()

        # Create a temp file for the cached path
        cached_path = Path("/tmp/test-correct-session.jsonl")
        cached_path.touch()

        try:
            session.codex_jsonl_path = cached_path
            mock_is_idle.return_value = True

            result = session.is_idle()

            assert result is True
            mock_is_idle.assert_called_once_with(cached_path)
            # Should NOT have called find_codex_session_by_internal_id
            mock_find.assert_not_called()
        finally:
            cached_path.unlink(missing_ok=True)


class TestCodexJsonlPathInToDict:
    """codex_jsonl_path must be serialized for event log persistence."""

    def test_to_dict_includes_codex_jsonl_path_when_set(self):
        """ManagedSession.to_dict() includes codex_jsonl_path as string."""
        mock_terminal = MagicMock()
        session = ManagedSession(
            session_id="test-123",
            terminal_session=mock_terminal,
            project_path="/test/path",
            agent_type="codex",
        )
        session.codex_jsonl_path = Path("/tmp/codex-session.jsonl")

        d = session.to_dict()

        assert d["codex_jsonl_path"] == "/tmp/codex-session.jsonl"

    def test_to_dict_includes_none_codex_jsonl_path(self):
        """ManagedSession.to_dict() includes None when codex_jsonl_path not set."""
        mock_terminal = MagicMock()
        session = ManagedSession(
            session_id="test-123",
            terminal_session=mock_terminal,
            project_path="/test/path",
            agent_type="claude",
        )

        d = session.to_dict()

        assert d["codex_jsonl_path"] is None


class TestRecoveredSessionCodexJsonlPath:
    """RecoveredSession must persist codex_jsonl_path from event data."""

    def test_recovered_session_includes_codex_jsonl_path(self):
        """RecoveredSession stores codex_jsonl_path from snapshot data."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Rick",
            project_path="/test/project",
            terminal_id=TerminalId("tmux", "%1"),
            agent_type="codex",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
            codex_jsonl_path="/codex/sessions/2026/02/05/rollout-abc.jsonl",
        )

        assert session.codex_jsonl_path == "/codex/sessions/2026/02/05/rollout-abc.jsonl"

    def test_recovered_session_to_dict_includes_codex_jsonl_path(self):
        """RecoveredSession.to_dict() includes codex_jsonl_path."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Rick",
            project_path="/test/project",
            terminal_id=None,
            agent_type="codex",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
            codex_jsonl_path="/codex/sessions/rollout.jsonl",
        )

        d = session.to_dict()

        assert d["codex_jsonl_path"] == "/codex/sessions/rollout.jsonl"

    def test_recovered_session_default_codex_jsonl_path_is_none(self):
        """RecoveredSession.codex_jsonl_path defaults to None."""
        now = datetime.now()
        session = RecoveredSession(
            session_id="abc12345",
            name="Morty",
            project_path="/test/project",
            terminal_id=None,
            agent_type="claude",
            status=SessionStatus.READY,
            last_activity=now,
            created_at=now,
            event_state="idle",
            recovered_at=now,
            last_event_ts=now,
        )

        assert session.codex_jsonl_path is None
        assert session.to_dict()["codex_jsonl_path"] is None


class TestRecoverFromEventsCodexJsonlPath:
    """recover_from_events must propagate codex_jsonl_path to RecoveredSession."""

    def test_codex_jsonl_path_recovered_from_snapshot(self):
        """codex_jsonl_path in worker snapshot data populates RecoveredSession."""
        from claude_team_mcp.registry import SessionRegistry

        registry = SessionRegistry()

        snapshot = {
            "ts": "2026-02-05T12:00:00Z",
            "workers": [
                {
                    "session_id": "codex-worker-1",
                    "name": "Rick",
                    "project_path": "/test/project",
                    "agent_type": "codex",
                    "state": "idle",
                    "codex_jsonl_path": "/codex/sessions/2026/02/05/rollout-xyz.jsonl",
                    "created_at": "2026-02-05T11:00:00Z",
                    "last_activity": "2026-02-05T11:30:00Z",
                },
            ],
        }

        report = registry.recover_from_events(snapshot, [])

        assert report.added == 1
        recovered = registry._recovered_sessions["codex-worker-1"]
        assert recovered.codex_jsonl_path == "/codex/sessions/2026/02/05/rollout-xyz.jsonl"
        assert recovered.agent_type == "codex"
