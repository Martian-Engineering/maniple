"""Idle detection based on file activity and process state."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AgentType = Literal["claude", "codex"]


@dataclass
class Worker:
    """Minimal worker state for idle detection."""

    project_path: str
    claude_session_id: str | None
    agent_type: AgentType
    is_idle: bool = False
    message_count: int | None = None
    last_message_count: int | None = None
    last_message_timestamp: float | None = None
    output_path: Path | None = None
    pid: int | None = None


def get_project_slug(project_path: str) -> str:
    """Convert a filesystem path to Claude's project directory slug."""
    return project_path.replace("/", "-").replace(".", "-")


def get_claude_jsonl_path(worker: Worker) -> Path | None:
    """Construct JSONL path for Claude Code worker."""
    if not worker.project_path or not worker.claude_session_id:
        return None
    project_slug = get_project_slug(worker.project_path)
    return Path.home() / ".claude" / "projects" / project_slug / f"{worker.claude_session_id}.jsonl"


def check_file_idle(path: Path, threshold_seconds: int) -> tuple[bool, int]:
    """Check if file mtime exceeds threshold, return (is_idle, age_seconds)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False, 0

    age_seconds = max(0, int(time.time() - mtime))
    return age_seconds >= threshold_seconds, age_seconds


# Compare message counts and update worker state when activity changes.
def _detect_idle_from_message_count(
    worker: Worker,
    idle_threshold_seconds: int,
) -> tuple[bool, str | None] | None:
    message_count = getattr(worker, "message_count", None)
    if message_count is None:
        return None

    now = time.time()
    last_count = getattr(worker, "last_message_count", None)
    last_timestamp = getattr(worker, "last_message_timestamp", None)

    if last_count is None or last_timestamp is None:
        # Seed tracking state on first observation.
        setattr(worker, "last_message_count", message_count)
        setattr(worker, "last_message_timestamp", now)
        return None

    if message_count != last_count:
        # Activity observed, reset tracking window.
        setattr(worker, "last_message_count", message_count)
        setattr(worker, "last_message_timestamp", now)
        return False, None

    idle_for = now - last_timestamp
    if idle_for >= idle_threshold_seconds:
        # No message activity within the threshold window.
        return True, f"message_count_stalled:{int(idle_for)}s"

    return False, None


# Best-effort process probe for Codex workers without output file updates.
def _detect_idle_from_process(worker: Worker) -> tuple[bool, str | None] | None:
    pid = getattr(worker, "pid", None)
    if not pid:
        return None

    try:
        # Raises OSError when the PID does not exist.
        os.kill(pid, 0)
    except OSError:
        return True, "process_exited"

    try:
        result = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    state = result.stdout.strip()
    if not state:
        return None

    # "S" (sleeping) is a best-effort proxy for waiting on stdin.
    if state[0] in {"S", "I"}:
        return True, "process_sleeping"

    return False, None


def detect_worker_idle(
    worker: Worker,
    idle_threshold_seconds: int = 300,
) -> tuple[bool, str | None]:
    """
    Detect if worker is idle based on file activity.

    Returns (is_idle, reason) where reason explains how idle was detected.
    """
    # Get current idle state, handling both attributes and methods
    current_idle_attr = getattr(worker, "is_idle", False)
    if callable(current_idle_attr):
        # ManagedSession has is_idle() method, call it
        try:
            current_idle = current_idle_attr()
        except Exception:
            current_idle = False
    else:
        current_idle = bool(current_idle_attr)

    # Claude workers: JSONL mtime is primary, message count is secondary.
    if worker.agent_type == "claude":
        jsonl_path = get_claude_jsonl_path(worker)
        if jsonl_path and jsonl_path.exists():
            is_idle, age_seconds = check_file_idle(jsonl_path, idle_threshold_seconds)
            if is_idle:
                return True, f"jsonl_mtime:{age_seconds}s"
            return False, None

        # Fall back to message count when the JSONL path is missing.
        message_result = _detect_idle_from_message_count(worker, idle_threshold_seconds)
        if message_result is not None:
            return message_result

        # No signal available, keep existing idle state.
        return current_idle, None

    # Codex workers: output file mtime is primary, process state is fallback.
    if worker.agent_type == "codex":
        output_path = getattr(worker, "output_path", None)
        if output_path and output_path.exists():
            is_idle, age_seconds = check_file_idle(output_path, idle_threshold_seconds)
            if is_idle:
                return True, f"output_mtime:{age_seconds}s"
            return False, None

        process_result = _detect_idle_from_process(worker)
        if process_result is not None:
            return process_result

        # Nothing to inspect, preserve current state.
        return current_idle, None

    return current_idle, "unknown_agent_type"
