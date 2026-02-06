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

2. Codex (Session File Polling):
   Codex writes session files to ~/.codex/sessions/YYYY/MM/DD/.
   We poll these files for agent_message events which indicate the agent
   has finished responding. The session file name contains the thread_id.
   Binary state model:
   - Idle: Last response_item with agent_message type exists, no subsequent user_message
   - Working: No agent_message yet, or user_message exists after the last agent_message
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import msgspec

from .schemas.codex import ThreadStarted, TurnCompleted, TurnFailed, TurnStarted, decode_event
from .session_state import is_session_stopped

logger = logging.getLogger("claude-team-mcp")

# Path to Codex session files
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def find_codex_session_file(
    thread_id: str | None = None,
    max_age_seconds: int = 300,
) -> Path | None:
    """
    Find a Codex session file in ~/.codex/sessions/.

    Searches for session files matching the given thread_id, or returns
    the most recent session file if no thread_id is specified.

    Session files are named: rollout-YYYY-MM-DDTHH-MM-SS-<thread_id>.jsonl

    Args:
        thread_id: Optional thread ID to search for. If None, returns most recent.
        max_age_seconds: Only consider files modified within this time (default 5 min)

    Returns:
        Path to the matching session file, or None if not found
    """
    if not CODEX_SESSIONS_DIR.exists():
        return None

    now = time.time()
    cutoff = now - max_age_seconds

    # Search recent date directories (today and yesterday)
    date_dirs: list[Path] = []
    for year_dir in sorted(CODEX_SESSIONS_DIR.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir(), reverse=True):
                if not day_dir.is_dir():
                    continue
                date_dirs.append(day_dir)
                # Limit to recent 3 days of directories
                if len(date_dirs) >= 3:
                    break
            if len(date_dirs) >= 3:
                break
        if len(date_dirs) >= 3:
            break

    candidates: list[tuple[float, Path]] = []

    for date_dir in date_dirs:
        for jsonl_file in date_dir.glob("rollout-*.jsonl"):
            # Check file age
            try:
                mtime = jsonl_file.stat().st_mtime
                if mtime < cutoff:
                    continue

                # If thread_id specified, check if it's in the filename
                if thread_id:
                    if thread_id in jsonl_file.name:
                        return jsonl_file
                else:
                    candidates.append((mtime, jsonl_file))

            except OSError:
                continue

    # If no thread_id specified, return most recent file
    if candidates and not thread_id:
        candidates.sort(reverse=True)  # Sort by mtime descending
        return candidates[0][1]

    return None


def get_codex_thread_id_from_session_file(jsonl_path: Path) -> str | None:
    """
    Extract the thread_id from a Codex session file name.

    Session files are named: rollout-YYYY-MM-DDTHH-MM-SS-<thread_id>.jsonl
    The thread_id is the last component before .jsonl.

    Args:
        jsonl_path: Path to the Codex session file

    Returns:
        The thread_id string if found, None otherwise
    """
    name = jsonl_path.stem  # Remove .jsonl
    # Format: rollout-2026-01-11T15-14-58-019baf57-64cb-7cc1-96bf-1d41751e40fc
    # The thread_id is a UUID after the timestamp
    parts = name.split("-")
    if len(parts) >= 8:
        # Thread ID is the last 5 parts (UUID format: 8-4-4-4-12 hex chars)
        # But looking at actual names, it appears to be everything after the timestamp
        # rollout-YYYY-MM-DDTHH-MM-SS-<thread_id>
        # We can extract from session_meta in the file instead
        pass

    # More reliable: extract from session_meta in the file
    try:
        with open(jsonl_path, "rb") as f:
            first_line = f.readline()
            if first_line:
                data = json.loads(first_line)
                if data.get("type") == "session_meta":
                    return data.get("payload", {}).get("id")
    except (OSError, json.JSONDecodeError):
        pass

    return None


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
    Check if a Codex session is idle by parsing the session JSONL file.

    For interactive mode session files (in ~/.codex/sessions/), idle detection
    works by checking the last events in the file:
    - If the last response_item has type "message" with role "assistant" or
      has payload.type "agent_message", the agent has responded and is idle
    - If there's a user_message after the last agent response, still working

    For exec mode (legacy capture files), checks for TurnCompleted/TurnFailed events.

    Args:
        jsonl_path: Path to the Codex JSONL session file

    Returns:
        True if idle (agent responded), False if working or file not found
    """
    if not jsonl_path.exists():
        return False

    try:
        file_size = jsonl_path.stat().st_size
        if file_size == 0:
            return False

        # Read last 50KB for efficiency
        read_size = min(file_size, 50000)
        with open(jsonl_path, "rb") as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
                f.readline()  # Skip partial first line
            content = f.read()

        lines = content.strip().split(b"\n")

        # Track the last significant events
        last_agent_response_idx = -1
        last_user_message_idx = -1

        for i, line in enumerate(lines):
            if not line.strip():
                continue

            try:
                data = json.loads(line)

                # Check for interactive mode format (wrapped events)
                if data.get("type") == "event_msg":
                    payload = data.get("payload", {})
                    payload_type = payload.get("type")
                    # agent_message indicates agent finished responding
                    if payload_type == "agent_message":
                        last_agent_response_idx = i
                    # user_message indicates new input
                    elif payload_type == "user_message":
                        last_user_message_idx = i

                elif data.get("type") == "response_item":
                    payload = data.get("payload", {})
                    payload_type = payload.get("type")
                    role = payload.get("role")
                    # message with role=assistant indicates agent response
                    if payload_type == "message" and role == "assistant":
                        last_agent_response_idx = i
                    # message with role=user indicates user input
                    elif payload_type == "message" and role == "user":
                        last_user_message_idx = i
                    # agent_message type in payload
                    elif payload_type == "agent_message":
                        last_agent_response_idx = i

                # Check for exec mode format (direct events)
                else:
                    event_type = data.get("type")
                    if event_type in ("turn.completed", "turn.failed"):
                        last_agent_response_idx = i
                    elif event_type == "turn.started":
                        last_user_message_idx = i

            except json.JSONDecodeError:
                # Try msgspec for exec mode format
                try:
                    event = decode_event(line)
                    if isinstance(event, (TurnCompleted, TurnFailed)):
                        last_agent_response_idx = i
                    elif isinstance(event, TurnStarted):
                        last_user_message_idx = i
                except msgspec.DecodeError:
                    continue

        # Idle if we have an agent response and no user message after it
        if last_agent_response_idx >= 0:
            return last_user_message_idx < last_agent_response_idx

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
    agent_type: str = "claude"


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
            if session.agent_type == "codex":
                idle = is_codex_idle(session.jsonl_path)
            else:
                idle = is_idle(session.jsonl_path, session.session_id)
            if idle:
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
            if session.agent_type == "codex":
                idle = is_codex_idle(session.jsonl_path)
            else:
                idle = is_idle(session.jsonl_path, session.session_id)
            if idle:
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
        if session.agent_type == "codex":
            idle = is_codex_idle(session.jsonl_path)
        else:
            idle = is_idle(session.jsonl_path, session.session_id)
        if idle:
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
