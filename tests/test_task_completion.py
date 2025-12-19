"""
Tests for task completion detection (Stop hook based).
"""

import pytest
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
import json

from claude_team_mcp.task_completion import (
    TaskStatus,
    TaskCompletionInfo,
    detect_completion,
)


class TestStopHookDetection:
    """Test Stop hook-based completion detection."""

    def _write_jsonl(self, entries: list[dict]) -> Path:
        """Write test JSONL entries to a temp file."""
        f = NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.close()
        return Path(f.name)

    def test_completed_when_stop_hook_fired(self):
        """Test detection when Stop hook has fired with no subsequent messages."""
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

        result = detect_completion(jsonl_path, session_id)
        assert result.status == TaskStatus.COMPLETED
        assert result.detection_method == "stop_hook"

        # Cleanup
        jsonl_path.unlink()

    def test_in_progress_when_no_stop_hook(self):
        """Test detection when no Stop hook has fired."""
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

        result = detect_completion(jsonl_path, session_id)
        assert result.status == TaskStatus.IN_PROGRESS

        jsonl_path.unlink()

    def test_in_progress_when_message_after_stop_hook(self):
        """Test detection when user sent message after Stop hook (new task)."""
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

        result = detect_completion(jsonl_path, session_id)
        assert result.status == TaskStatus.IN_PROGRESS

        jsonl_path.unlink()

    def test_unknown_when_no_jsonl(self):
        """Test detection when JSONL file doesn't exist."""
        result = detect_completion(Path("/nonexistent/path.jsonl"), "abc123")
        assert result.status == TaskStatus.UNKNOWN

    def test_wrong_session_id_not_detected(self):
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

        result = detect_completion(jsonl_path, "my-session")
        assert result.status == TaskStatus.IN_PROGRESS

        jsonl_path.unlink()


class TestTaskCompletionInfo:
    """Test TaskCompletionInfo serialization."""

    def test_to_dict(self):
        """Test TaskCompletionInfo serializes correctly."""
        info = TaskCompletionInfo(
            status=TaskStatus.COMPLETED,
            detection_method="stop_hook",
            details={"session_id": "abc123"},
        )

        result = info.to_dict()
        assert result["status"] == "completed"
        assert result["detection_method"] == "stop_hook"
        assert "detected_at" in result
        # No confidence field anymore
        assert "confidence" not in result
