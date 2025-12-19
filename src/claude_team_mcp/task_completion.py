"""
Task Completion Detection

Detects when a delegated task is complete using Stop hook signals.

Workers are spawned with a Stop hook that fires when Claude finishes responding.
The hook embeds a session ID marker in the JSONL, providing authoritative
completion detection. Either the hook fired (done) or it hasn't (not done).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .session_state import is_session_stopped

logger = logging.getLogger("claude-team-mcp")


class TaskStatus(str, Enum):
    """Status of a delegated task."""

    COMPLETED = "completed"  # Task finished (Stop hook fired, no messages after)
    IN_PROGRESS = "in_progress"  # Task still running
    UNKNOWN = "unknown"  # Cannot determine (no JSONL, etc.)


@dataclass
class TaskCompletionInfo:
    """Information about task completion status."""

    status: TaskStatus
    detection_method: str = "stop_hook"
    details: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP tool responses."""
        return {
            "status": self.status.value,
            "detection_method": self.detection_method,
            "details": self.details,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class TaskContext:
    """Context for tracking a delegated task."""

    session_id: str
    project_path: str
    started_at: datetime
    task_description: Optional[str] = None


def detect_completion(jsonl_path: Path, session_id: str) -> TaskCompletionInfo:
    """
    Check if a session has completed via Stop hook.

    Args:
        jsonl_path: Path to the session JSONL file
        session_id: The session ID (matches marker in Stop hook)

    Returns:
        TaskCompletionInfo with COMPLETED if done, IN_PROGRESS if not
    """
    if not jsonl_path.exists():
        return TaskCompletionInfo(
            status=TaskStatus.UNKNOWN,
            details={"reason": "JSONL file not found"},
        )

    if is_session_stopped(jsonl_path, session_id):
        return TaskCompletionInfo(
            status=TaskStatus.COMPLETED,
            details={
                "session_id": session_id,
                "signal": "stop_hook fired with no subsequent messages",
            },
        )

    return TaskCompletionInfo(
        status=TaskStatus.IN_PROGRESS,
        details={"session_id": session_id},
    )


async def wait_for_completion(
    jsonl_path: Path,
    session_id: str,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
) -> TaskCompletionInfo:
    """
    Wait for a session to complete.

    Polls until the Stop hook fires or timeout is reached.

    Args:
        jsonl_path: Path to session JSONL file
        session_id: The session ID to check
        timeout: Maximum seconds to wait
        poll_interval: Seconds between checks

    Returns:
        TaskCompletionInfo with final status
    """
    import time

    start = time.time()

    while time.time() - start < timeout:
        result = detect_completion(jsonl_path, session_id)

        if result.status == TaskStatus.COMPLETED:
            result.details["waited_seconds"] = time.time() - start
            return result

        await asyncio.sleep(poll_interval)

    # Timeout
    return TaskCompletionInfo(
        status=TaskStatus.IN_PROGRESS,
        details={
            "session_id": session_id,
            "timeout": True,
            "waited_seconds": timeout,
        },
    )
