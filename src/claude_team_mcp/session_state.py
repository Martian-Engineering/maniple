"""
Claude Session State Parser

Parse Claude Code session JSONL files to read conversation state.
Extracted and adapted from session_parser.py for use in the MCP server.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterator


# Claude projects directory
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Message:
    """A single message from a Claude session."""

    uuid: str
    parent_uuid: Optional[str]
    role: str  # "user" or "assistant"
    content: str  # Extracted text content
    timestamp: datetime
    tool_uses: list = field(default_factory=list)

    def __repr__(self) -> str:
        preview = self.content[:40] + "..." if len(self.content) > 40 else self.content
        return f"Message({self.role}: {preview!r})"


@dataclass
class SessionState:
    """Parsed state of a Claude session from its JSONL file."""

    session_id: str
    project_path: str
    jsonl_path: Path
    messages: list[Message] = field(default_factory=list)
    last_modified: float = 0

    @property
    def last_user_message(self) -> Optional[Message]:
        """Get the most recent user message."""
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg
        return None

    @property
    def last_assistant_message(self) -> Optional[Message]:
        """Get the most recent assistant message with text content."""
        for msg in reversed(self.messages):
            if msg.role == "assistant" and msg.content:
                return msg
        return None

    @property
    def conversation(self) -> list[Message]:
        """Get only user/assistant messages with content."""
        return [m for m in self.messages if m.role in ("user", "assistant") and m.content]

    @property
    def is_processing(self) -> bool:
        """Check if Claude appears to be processing (last msg has tool_use)."""
        if not self.messages:
            return False
        last = self.messages[-1]
        return bool(last.tool_uses)

    @property
    def message_count(self) -> int:
        """Total number of conversation messages."""
        return len(self.conversation)


# =============================================================================
# Path Utilities
# =============================================================================

def get_project_slug(project_path: str) -> str:
    """
    Convert a filesystem path to Claude's project directory slug.

    Claude replaces / with - to create directory names.
    Example: /Users/josh/code -> -Users-josh-code
    """
    return project_path.replace("/", "-")


def get_project_dir(project_path: str) -> Path:
    """
    Get the Claude projects directory for a given project path.

    Args:
        project_path: Absolute path to the project

    Returns:
        Path to the Claude projects directory for this project
    """
    return CLAUDE_PROJECTS_DIR / get_project_slug(project_path)


# =============================================================================
# Session Discovery
# =============================================================================

def list_sessions(project_path: str) -> list[tuple[str, Path, float]]:
    """
    List all Claude sessions for a project.

    Args:
        project_path: Absolute path to the project

    Returns:
        List of (session_id, jsonl_path, mtime) sorted by mtime desc
    """
    project_dir = get_project_dir(project_path)
    if not project_dir.exists():
        return []

    sessions = []
    for f in project_dir.glob("*.jsonl"):
        # Skip agent-* files (subagents)
        if f.name.startswith("agent-"):
            continue
        sessions.append((f.stem, f, f.stat().st_mtime))

    return sorted(sessions, key=lambda x: x[2], reverse=True)


def find_active_session(project_path: str, max_age_seconds: int = 300) -> Optional[str]:
    """
    Find the most recently active session (modified within max_age_seconds).

    Useful for identifying which JSONL file corresponds to a running Claude instance.

    Args:
        project_path: Absolute path to the project
        max_age_seconds: Maximum age in seconds to consider "active"

    Returns:
        Session ID string, or None if no active session found
    """
    sessions = list_sessions(project_path)
    if not sessions:
        return None

    session_id, _, mtime = sessions[0]
    if time.time() - mtime < max_age_seconds:
        return session_id
    return None


# =============================================================================
# Session Parsing
# =============================================================================

def parse_session(jsonl_path: Path) -> SessionState:
    """
    Parse a Claude session JSONL file into a SessionState object.

    The JSONL format has one JSON object per line with structure:
    {
        "type": "user" | "assistant" | "file-history-snapshot",
        "sessionId": "uuid",
        "uuid": "message-uuid",
        "parentUuid": "parent-uuid",
        "message": { "role": "user"|"assistant", "content": [...] },
        "timestamp": "ISO-8601",
        "cwd": "/path/to/project"
    }

    Args:
        jsonl_path: Path to the JSONL file

    Returns:
        Parsed SessionState object
    """
    messages = []
    session_id = jsonl_path.stem
    project_path = ""

    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip non-message entries
            if entry.get("type") == "file-history-snapshot":
                continue

            # Extract project path from cwd if available
            if "cwd" in entry and not project_path:
                project_path = entry["cwd"]

            # Parse message content
            message_data = entry.get("message", {})
            role = message_data.get("role", "")
            raw_content = message_data.get("content", [])

            # Extract text content
            if isinstance(raw_content, str):
                text_content = raw_content
                tool_uses = []
            else:
                text_parts = []
                tool_uses = []
                for item in raw_content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "tool_use":
                            tool_uses.append(
                                {
                                    "id": item.get("id"),
                                    "name": item.get("name"),
                                    "input": item.get("input", {}),
                                }
                            )
                text_content = "\n".join(text_parts)

            # Parse timestamp
            try:
                ts = datetime.fromisoformat(
                    entry.get("timestamp", "").replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                ts = datetime.now()

            messages.append(
                Message(
                    uuid=entry.get("uuid", ""),
                    parent_uuid=entry.get("parentUuid"),
                    role=role,
                    content=text_content,
                    timestamp=ts,
                    tool_uses=tool_uses,
                )
            )

    return SessionState(
        session_id=session_id,
        project_path=project_path,
        jsonl_path=jsonl_path,
        messages=messages,
        last_modified=jsonl_path.stat().st_mtime if jsonl_path.exists() else 0,
    )


def watch_session(jsonl_path: Path, poll_interval: float = 0.5) -> Iterator[SessionState]:
    """
    Generator that yields SessionState whenever the file changes.

    Blocking iterator - use in a separate thread or with asyncio.to_thread().

    Args:
        jsonl_path: Path to the session JSONL file
        poll_interval: Seconds between checks

    Yields:
        SessionState objects when changes detected
    """
    last_mtime = 0.0
    last_size = 0

    while True:
        try:
            stat = jsonl_path.stat()
            if stat.st_mtime > last_mtime or stat.st_size > last_size:
                last_mtime = stat.st_mtime
                last_size = stat.st_size
                yield parse_session(jsonl_path)
        except FileNotFoundError:
            pass
        time.sleep(poll_interval)


# =============================================================================
# Response Waiting
# =============================================================================

async def wait_for_response(
    jsonl_path: Path,
    timeout: float = 120,
    poll_interval: float = 0.5,
    idle_threshold: float = 2.0,
    baseline_message_uuid: Optional[str] = None,
) -> Optional[Message]:
    """
    Wait for Claude to finish responding.

    Monitors the JSONL file for a new assistant message. Returns when:
    1. A new assistant message exists (different from baseline_message_uuid)
    2. AND the file has been idle for idle_threshold seconds

    Args:
        jsonl_path: Path to the session JSONL file
        timeout: Maximum seconds to wait
        poll_interval: Seconds between checks
        idle_threshold: Seconds of no changes before considering complete
        baseline_message_uuid: UUID of the last assistant message before sending.
            If provided, waits for a DIFFERENT message to appear.

    Returns:
        The last assistant message, or None if timeout
    """
    import asyncio

    start = time.time()
    last_mtime = jsonl_path.stat().st_mtime if jsonl_path.exists() else 0.0
    last_change = start

    # Brief initial delay for Claude to start processing
    await asyncio.sleep(0.5)

    while time.time() - start < timeout:
        try:
            stat = jsonl_path.stat()
            current_mtime = stat.st_mtime

            # Track file modifications
            if current_mtime > last_mtime:
                last_mtime = current_mtime
                last_change = time.time()

            # Check if idle long enough
            idle_time = time.time() - last_change
            if idle_time >= idle_threshold:
                # Parse and check for new response
                state = parse_session(jsonl_path)
                last_msg = state.last_assistant_message

                if last_msg:
                    # If no baseline provided, return any assistant message
                    if baseline_message_uuid is None:
                        return last_msg
                    # If baseline provided, only return if it's a NEW message
                    if last_msg.uuid != baseline_message_uuid:
                        return last_msg
                    # Same message as baseline - keep waiting for new one

        except FileNotFoundError:
            pass

        await asyncio.sleep(poll_interval)

    return None
