"""
Tests for idle detection (Stop hook based and Codex JSONL based).
"""

import asyncio
from pathlib import Path
from tempfile import NamedTemporaryFile
import json

from maniple_mcp.idle_detection import (
    is_idle,
    is_codex_idle,
    wait_for_idle,
    wait_for_any_idle,
    wait_for_all_idle,
    SessionInfo,
    DEFAULT_TIMEOUT,
)



class TestIsIdle:
    """Test is_idle function."""

    def _write_jsonl(self, entries: list[dict]) -> Path:
        """Write test JSONL entries to a temp file."""
        f = NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.close()
        return Path(f.name)

    def test_idle_when_stop_hook_fired(self):
        """Test is_idle returns True when Stop hook has fired with no subsequent messages."""
        session_id = "abc123"
        entries = [
            {
                "type": "user",
                "message": {"content": "Do something"},
                "timestamp": "2025-01-01T10:00:00Z",
                "uuid": "u1",
            },
            {
                "type": "assistant",
                "message": {"content": "Done."},
                "timestamp": "2025-01-01T10:00:05Z",
                "uuid": "a1",
            },
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hookInfos": [{"command": f"echo [worker-done:{session_id}]"}],
                "timestamp": "2025-01-01T10:00:06Z",
                "uuid": "s1",
            },
        ]
        jsonl_path = self._write_jsonl(entries)

        result = is_idle(jsonl_path, session_id)
        assert result is True

        # Cleanup
        jsonl_path.unlink()

    def test_not_idle_when_no_stop_hook(self):
        """Test is_idle returns False when no Stop hook has fired."""
        session_id = "abc123"
        entries = [
            {
                "type": "user",
                "message": {"content": "Do something"},
                "timestamp": "2025-01-01T10:00:00Z",
                "uuid": "u1",
            },
            {
                "type": "assistant",
                "message": {"content": "Working on it..."},
                "timestamp": "2025-01-01T10:00:05Z",
                "uuid": "a1",
            },
        ]
        jsonl_path = self._write_jsonl(entries)

        result = is_idle(jsonl_path, session_id)
        assert result is False

        jsonl_path.unlink()

    def test_not_idle_when_message_after_stop_hook(self):
        """Test is_idle returns False when user sent message after Stop hook (new task)."""
        session_id = "abc123"
        entries = [
            {
                "type": "assistant",
                "message": {"content": "Done."},
                "timestamp": "2025-01-01T10:00:05Z",
                "uuid": "a1",
            },
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hookInfos": [{"command": f"echo [worker-done:{session_id}]"}],
                "timestamp": "2025-01-01T10:00:06Z",
                "uuid": "s1",
            },
            {
                "type": "user",
                "message": {"content": "Now do something else"},
                "timestamp": "2025-01-01T10:00:10Z",
                "uuid": "u2",
            },
        ]
        jsonl_path = self._write_jsonl(entries)

        result = is_idle(jsonl_path, session_id)
        assert result is False

        jsonl_path.unlink()

    def test_not_idle_when_no_jsonl(self):
        """Test is_idle returns False when JSONL file doesn't exist."""
        result = is_idle(Path("/nonexistent/path.jsonl"), "abc123")
        assert result is False

    def test_not_idle_when_wrong_session_id(self):
        """Test that Stop hook for different session ID is not detected."""
        entries = [
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hookInfos": [{"command": "echo [worker-done:other-session]"}],
                "timestamp": "2025-01-01T10:00:06Z",
                "uuid": "s1",
            },
        ]
        jsonl_path = self._write_jsonl(entries)

        result = is_idle(jsonl_path, "my-session")
        assert result is False

        jsonl_path.unlink()


class TestDefaultTimeout:
    """Test default timeout value."""

    def test_default_timeout_is_600_seconds(self):
        """Test that DEFAULT_TIMEOUT is 600 seconds (10 minutes)."""
        assert DEFAULT_TIMEOUT == 600.0


class TestWaitForIdle:
    """Test wait_for_idle function."""

    def _write_jsonl(self, entries: list[dict]) -> Path:
        """Write test JSONL entries to a temp file."""
        f = NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.close()
        return Path(f.name)

    def test_wait_for_idle_already_idle(self):
        """Test wait_for_idle returns immediately when session is already idle."""
        session_id = "abc123"
        entries = [
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hookInfos": [{"command": f"echo [worker-done:{session_id}]"}],
                "timestamp": "2025-01-01T10:00:06Z",
                "uuid": "s1",
            },
        ]
        jsonl_path = self._write_jsonl(entries)

        result = asyncio.run(wait_for_idle(jsonl_path, session_id, timeout=1.0))
        assert result["idle"] is True
        assert result["session_id"] == session_id
        assert result["timed_out"] is False
        assert result["waited_seconds"] < 1.0

        jsonl_path.unlink()

    def test_wait_for_idle_timeout(self):
        """Test wait_for_idle times out when session never becomes idle."""
        session_id = "abc123"
        entries = [
            {
                "type": "user",
                "message": {"content": "Do something"},
                "timestamp": "2025-01-01T10:00:00Z",
                "uuid": "u1",
            },
        ]
        jsonl_path = self._write_jsonl(entries)

        result = asyncio.run(wait_for_idle(jsonl_path, session_id, timeout=0.5, poll_interval=0.1))
        assert result["idle"] is False
        assert result["timed_out"] is True
        assert result["waited_seconds"] >= 0.5

        jsonl_path.unlink()


class TestCohortIdleDetection:
    """Test wait_for_any_idle and wait_for_all_idle functions."""

    def _write_jsonl(self, entries: list[dict]) -> Path:
        """Write test JSONL entries to a temp file."""
        f = NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.close()
        return Path(f.name)

    def _make_idle_entries(self, session_id: str) -> list[dict]:
        """Create JSONL entries for an idle session."""
        return [
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "hookInfos": [{"command": f"echo [worker-done:{session_id}]"}],
                "timestamp": "2025-01-01T10:00:06Z",
                "uuid": "s1",
            },
        ]

    def _make_working_entries(self) -> list[dict]:
        """Create JSONL entries for a working session."""
        return [
            {
                "type": "user",
                "message": {"content": "Do something"},
                "timestamp": "2025-01-01T10:00:00Z",
                "uuid": "u1",
            },
        ]

    def test_wait_for_any_idle_one_of_two(self):
        """Test wait_for_any_idle returns when first session becomes idle."""
        session1 = "session1"
        session2 = "session2"

        # Session1 is idle, session2 is working
        path1 = self._write_jsonl(self._make_idle_entries(session1))
        path2 = self._write_jsonl(self._make_working_entries())

        sessions = [
            SessionInfo(jsonl_path=path1, session_id=session1),
            SessionInfo(jsonl_path=path2, session_id=session2),
        ]

        result = asyncio.run(wait_for_any_idle(sessions, timeout=1.0))
        assert result["idle"] is True
        assert result["idle_session_id"] == session1
        assert result["timed_out"] is False

        path1.unlink()
        path2.unlink()

    def test_wait_for_all_idle_both_idle(self):
        """Test wait_for_all_idle returns when all sessions are idle."""
        session1 = "session1"
        session2 = "session2"

        # Both sessions are idle
        path1 = self._write_jsonl(self._make_idle_entries(session1))
        path2 = self._write_jsonl(self._make_idle_entries(session2))

        sessions = [
            SessionInfo(jsonl_path=path1, session_id=session1),
            SessionInfo(jsonl_path=path2, session_id=session2),
        ]

        result = asyncio.run(wait_for_all_idle(sessions, timeout=1.0))
        assert result["all_idle"] is True
        assert set(result["idle_session_ids"]) == {session1, session2}
        assert result["waiting_on"] == []
        assert result["timed_out"] is False

        path1.unlink()
        path2.unlink()

    def test_wait_for_all_idle_partial_timeout(self):
        """Test wait_for_all_idle times out with partial completion."""
        session1 = "session1"
        session2 = "session2"

        # Session1 is idle, session2 is working
        path1 = self._write_jsonl(self._make_idle_entries(session1))
        path2 = self._write_jsonl(self._make_working_entries())

        sessions = [
            SessionInfo(jsonl_path=path1, session_id=session1),
            SessionInfo(jsonl_path=path2, session_id=session2),
        ]

        result = asyncio.run(wait_for_all_idle(sessions, timeout=0.5, poll_interval=0.1))
        assert result["all_idle"] is False
        assert session1 in result["idle_session_ids"]
        assert session2 in result["waiting_on"]
        assert result["timed_out"] is True

        path1.unlink()
        path2.unlink()


class TestIsCodexIdle:
    """Test Codex idle detection via JSONL parsing."""

    def _write_codex_jsonl(self, lines: list[str]) -> Path:
        """Write Codex JSONL lines to a temp file."""
        f = NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for line in lines:
            f.write(line.strip() + "\n")
        f.close()
        return Path(f.name)

    def test_idle_when_turn_completed(self):
        """Test is_codex_idle returns True when TurnCompleted event is present."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"type":"agent_message","id":"m1","text":"Done"}}',
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":50}}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        result = is_codex_idle(jsonl_path)
        assert result is True

        jsonl_path.unlink()

    def test_idle_when_turn_failed(self):
        """Test is_codex_idle returns True when TurnFailed event is present."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
            '{"type":"turn.failed","error":{"message":"Rate limit exceeded"}}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        result = is_codex_idle(jsonl_path)
        assert result is True

        jsonl_path.unlink()

    def test_not_idle_when_turn_started(self):
        """Test is_codex_idle returns False when only TurnStarted is present."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        result = is_codex_idle(jsonl_path)
        assert result is False

        jsonl_path.unlink()

    def test_not_idle_when_new_turn_started_after_completion(self):
        """Test is_codex_idle returns False when new turn started after previous completed."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":50}}',
            '{"type":"turn.started"}',  # New turn started
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        result = is_codex_idle(jsonl_path)
        assert result is False

        jsonl_path.unlink()

    def test_not_idle_when_empty_file(self):
        """Test is_codex_idle returns False for empty file."""
        jsonl_path = self._write_codex_jsonl([])
        # File is empty, but exists
        with open(jsonl_path, "w") as f:
            pass  # Create empty file

        result = is_codex_idle(jsonl_path)
        assert result is False

        jsonl_path.unlink()

    def test_not_idle_when_file_not_exists(self):
        """Test is_codex_idle returns False when file doesn't exist."""
        result = is_codex_idle(Path("/nonexistent/codex.jsonl"))
        assert result is False

    def test_not_idle_when_only_thread_started(self):
        """Test is_codex_idle returns False when only ThreadStarted is present."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        result = is_codex_idle(jsonl_path)
        assert result is False

        jsonl_path.unlink()

    def test_idle_ignores_item_events(self):
        """Test is_codex_idle correctly ignores item events and finds turn events."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
            '{"type":"item.started","item":{"type":"agent_message","id":"m1","text":"Working..."}}',
            '{"type":"item.completed","item":{"type":"agent_message","id":"m1","text":"Working..."}}',
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":50}}',
            '{"type":"item.started","item":{"type":"agent_message","id":"m2","text":"Final note"}}',
            '{"type":"item.completed","item":{"type":"agent_message","id":"m2","text":"Final note"}}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        # Even though there are item events after TurnCompleted, the session is idle
        # because TurnCompleted is the last turn-related event
        result = is_codex_idle(jsonl_path)
        assert result is True

        jsonl_path.unlink()

    def test_handles_malformed_lines(self):
        """Test is_codex_idle gracefully handles malformed JSON lines."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
            '{malformed json}',
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":50}}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        result = is_codex_idle(jsonl_path)
        assert result is True

        jsonl_path.unlink()

    def test_handles_partial_writes(self):
        """Test is_codex_idle handles files with incomplete final line."""
        lines = [
            '{"type":"thread.started","thread_id":"thread_abc"}',
            '{"type":"turn.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":50}}',
        ]
        jsonl_path = self._write_codex_jsonl(lines)

        # Append a partial line (simulating in-progress write)
        with open(jsonl_path, "a") as f:
            f.write('{"type":"turn.sta')  # Incomplete line

        result = is_codex_idle(jsonl_path)
        assert result is True  # Should still detect the completed turn

        jsonl_path.unlink()
