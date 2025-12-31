"""
Idle Detection for Claude Team Workers

Detects when workers are idle (finished responding) using Stop hook signals.
Workers are spawned with a Stop hook that fires when Claude finishes responding.
The hook embeds a session ID marker in the JSONL - if it fired with no subsequent
messages, the worker is idle.

Binary state model:
- Idle: Stop hook fired, no messages after it
- Working: Either no stop hook yet, or messages exist after the last one
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .session_state import is_session_stopped

logger = logging.getLogger("claude-team-mcp")

# Default timeout for waiting operations (10 minutes)
DEFAULT_TIMEOUT = 600.0
DEFAULT_POLL_INTERVAL = 2.0


def is_idle(jsonl_path: Path, session_id: str) -> bool:
    """
    Check if a session is idle (finished responding).

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
