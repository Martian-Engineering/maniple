"""
Idle Detection for Claude Team Workers

Supports two detection modes:

1. Claude Code (Stop Hook Detection):
   Workers are spawned with a Stop hook that fires when Claude finishes responding.
   The hook embeds a session ID marker in the JSONL - if it fired with no subsequent
   messages, the worker is idle.
   Binary state model:
   - Idle: Stop hook fired, no messages after it
   - Working: Either no stop hook yet, or messages exist after the last one

2. Codex (JSONL Event Detection):
   Codex streams JSONL events to stdout. We pipe this through tee to capture it.
   A turn is complete when we see TurnCompleted or TurnFailed events.
   Binary state model:
   - Idle: Last event is TurnCompleted or TurnFailed
   - Working: No terminal event yet, or new TurnStarted after last terminal
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import msgspec

from .schemas.codex import ThreadStarted, TurnCompleted, TurnFailed, TurnStarted, decode_event
from .session_state import is_session_stopped

logger = logging.getLogger("claude-team-mcp")


def get_codex_thread_id(jsonl_path: Path) -> str | None:
    """
    Extract the thread_id from a Codex session's JSONL output.

    Parses the JSONL file looking for a ThreadStarted event, which contains
    the thread_id needed for session resume commands.

    The ThreadStarted event is typically near the beginning of the file,
    but we read from the start to find it reliably.

    Args:
        jsonl_path: Path to the Codex JSONL output file

    Returns:
        The thread_id string if found, None otherwise
    """
    if not jsonl_path.exists():
        return None

    try:
        # Read the first portion of the file (ThreadStarted is near the beginning)
        # Limit read to first 10KB to avoid loading huge files
        with open(jsonl_path, "rb") as f:
            content = f.read(10000)

        # Parse lines looking for ThreadStarted
        lines = content.strip().split(b"\n")

        for line in lines:
            if not line.strip():
                continue

            try:
                event = decode_event(line)

                # Check for ThreadStarted which contains thread_id
                if isinstance(event, ThreadStarted):
                    return event.thread_id

            except Exception:
                # Skip malformed lines (could be partial at end of read)
                continue

        # No ThreadStarted found
        return None

    except (OSError, IOError) as e:
        logger.warning(f"Error reading Codex JSONL {jsonl_path}: {e}")
        return None

# Default timeout for waiting operations (10 minutes)
DEFAULT_TIMEOUT = 600.0
DEFAULT_POLL_INTERVAL = 2.0


def is_idle(jsonl_path: Path, session_id: str) -> bool:
    """
    Check if a Claude Code session is idle (finished responding).

    A session is idle if its Stop hook has fired and no messages
    have been sent after it.

    Args:
        jsonl_path: Path to the session JSONL file
        session_id: The session ID (matches marker in Stop hook)

    Returns:
        True if idle, False if working or file not found
    """
    if not jsonl_path.exists():
        return False
    return is_session_stopped(jsonl_path, session_id)


def is_codex_idle(jsonl_path: Path) -> bool:
    """
    Check if a Codex session is idle by parsing JSONL for terminal events.

    A Codex session is idle if:
    1. The JSONL contains at least one TurnCompleted or TurnFailed event
    2. The last turn-related event is TurnCompleted or TurnFailed
       (not TurnStarted, which would indicate a new turn began)

    We parse from the end of the file for efficiency, since the terminal
    event will be near the end.

    Args:
        jsonl_path: Path to the Codex JSONL output file

    Returns:
        True if idle (turn completed/failed), False if working or file not found
    """
    if not jsonl_path.exists():
        return False

    try:
        # Read from the end of the file for efficiency
        # Most JSONL files are small enough to read entirely, but for large files
        # we only need to check the last few KB for the terminal event
        file_size = jsonl_path.stat().st_size
        if file_size == 0:
            return False

        # Read last 50KB (should be more than enough for terminal events)
        read_size = min(file_size, 50000)
        with open(jsonl_path, "rb") as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
                # Skip partial first line
                f.readline()
            content = f.read()

        # Parse lines from end to find the last turn-related event
        lines = content.strip().split(b"\n")

        # Scan from end looking for turn lifecycle events
        for line in reversed(lines):
            if not line.strip():
                continue

            try:
                event = decode_event(line)

                # Check for terminal events (turn finished)
                if isinstance(event, (TurnCompleted, TurnFailed)):
                    return True

                # If we hit a TurnStarted, a new turn began - not idle
                if isinstance(event, TurnStarted):
                    return False

            except msgspec.DecodeError:
                # Skip malformed lines (could be partial write)
                continue

        # No turn events found - session hasn't completed any turns yet
        return False

    except (OSError, IOError) as e:
        logger.warning(f"Error reading Codex JSONL {jsonl_path}: {e}")
        return False


async def wait_for_idle(
    jsonl_path: Path,
    session_id: str,
    timeout: float = DEFAULT_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    """
    Wait for a session to become idle.

    Polls until the Stop hook fires or timeout is reached.

    Args:
        jsonl_path: Path to session JSONL file
        session_id: The session ID to check
        timeout: Maximum seconds to wait (default 600s / 10 min)
        poll_interval: Seconds between checks

    Returns:
        Dict with {idle: bool, session_id: str, waited_seconds: float, timed_out: bool}
    """
    start = time.time()

    while time.time() - start < timeout:
        if is_idle(jsonl_path, session_id):
            return {
                "idle": True,
                "session_id": session_id,
                "waited_seconds": time.time() - start,
                "timed_out": False,
            }
        await asyncio.sleep(poll_interval)

    # Timeout
    return {
        "idle": False,
        "session_id": session_id,
        "waited_seconds": timeout,
        "timed_out": True,
    }


@dataclass
class SessionInfo:
    """Info needed to check a session's idle state."""

    jsonl_path: Path
    session_id: str


async def wait_for_any_idle(
    sessions: list[SessionInfo],
    timeout: float = DEFAULT_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    """
    Wait for ANY session to become idle.

    Returns as soon as the first session becomes idle.
    Useful for pipeline patterns where you want to process results
    as they become available.

    Args:
        sessions: List of SessionInfo to monitor
        timeout: Maximum seconds to wait
        poll_interval: Seconds between checks

    Returns:
        Dict with {
            idle_session_id: str | None,  # First session to become idle
            idle: bool,                    # True if any session became idle
            waited_seconds: float,
            timed_out: bool,
        }
    """
    start = time.time()

    while time.time() - start < timeout:
        for session in sessions:
            if is_idle(session.jsonl_path, session.session_id):
                return {
                    "idle_session_id": session.session_id,
                    "idle": True,
                    "waited_seconds": time.time() - start,
                    "timed_out": False,
                }
        await asyncio.sleep(poll_interval)

    return {
        "idle_session_id": None,
        "idle": False,
        "waited_seconds": timeout,
        "timed_out": True,
    }


async def wait_for_all_idle(
    sessions: list[SessionInfo],
    timeout: float = DEFAULT_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    """
    Wait for ALL sessions to become idle.

    Returns when every session has become idle, or on timeout.
    Useful for fan-out/fan-in patterns where you need all results
    before proceeding.

    Args:
        sessions: List of SessionInfo to monitor
        timeout: Maximum seconds to wait
        poll_interval: Seconds between checks

    Returns:
        Dict with {
            idle_session_ids: list[str],   # Sessions that are idle
            all_idle: bool,                 # True if all sessions became idle
            waiting_on: list[str],          # Sessions still working (if timed out)
            waited_seconds: float,
            timed_out: bool,
        }
    """
    start = time.time()

    while time.time() - start < timeout:
        idle_sessions = []
        working_sessions = []

        for session in sessions:
            if is_idle(session.jsonl_path, session.session_id):
                idle_sessions.append(session.session_id)
            else:
                working_sessions.append(session.session_id)

        if not working_sessions:
            # All idle!
            return {
                "idle_session_ids": idle_sessions,
                "all_idle": True,
                "waiting_on": [],
                "waited_seconds": time.time() - start,
                "timed_out": False,
            }

        await asyncio.sleep(poll_interval)

    # Timeout - return final state
    idle_sessions = []
    working_sessions = []
    for session in sessions:
        if is_idle(session.jsonl_path, session.session_id):
            idle_sessions.append(session.session_id)
        else:
            working_sessions.append(session.session_id)

    return {
        "idle_session_ids": idle_sessions,
        "all_idle": False,
        "waiting_on": working_sessions,
        "waited_seconds": timeout,
        "timed_out": True,
    }
