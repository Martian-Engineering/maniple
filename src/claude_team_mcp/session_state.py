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
from typing import Any, Optional


# Claude projects directory
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
# Codex sessions directory
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def parse_timestamp(entry: dict) -> datetime:
    """Parse ISO timestamp from JSONL entry, handling Z suffix."""
    try:
        return datetime.fromisoformat(
            entry.get("timestamp", "").replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        return datetime.now()


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
    thinking: Optional[str] = None  # Thinking block content if present

    def __repr__(self) -> str:
        preview = self.content[:40] + "..." if len(self.content) > 40 else self.content
        return f"Message({self.role}: {preview!r})"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.tool_uses:
            result["tool_uses"] = self.tool_uses
        if self.thinking:
            result["thinking"] = self.thinking
        return result


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
    def message_count(self) -> int:
        """Total number of conversation messages."""
        return len(self.conversation)


# =============================================================================
# Path Utilities
# =============================================================================

def get_project_slug(project_path: str) -> str:
    """
    Convert a filesystem path to Claude's project directory slug.

    Claude replaces both / and . with - to create directory names.
    Example: /Users/josh/code -> -Users-josh-code
    Example: /path/.worktrees/foo -> -path--worktrees-foo
    """
    return project_path.replace("/", "-").replace(".", "-")


def unslugify_path(slug: str) -> str | None:
    """
    Convert a Claude project slug back to a filesystem path.

    The slug replaces / with -, but project names can also contain -.
    We resolve the ambiguity by checking which paths actually exist.

    Args:
        slug: Claude project directory slug (e.g., "-Users-phaedrus-Projects-myproject")

    Returns:
        The original filesystem path if it can be determined, None otherwise.

    Example:
        "-Users-phaedrus-Projects-claude-iterm-controller"
        -> "/Users/phaedrus/Projects/claude-iterm-controller"
    """
    if not slug.startswith("-"):
        return None

    # Handle dotfile directories specifically
    # The slug replaces both / and . with -, so /.worktrees becomes --worktrees
    # We handle known cases to avoid unexpected behavior elsewhere
    slug = slug.replace("--worktrees", "-.worktrees")
    slug = slug.replace("--claude-team", "-.claude-team")

    # Split the slug into parts (removing the leading -)
    # Each part was originally separated by / or is part of a hyphenated name
    parts = slug[1:].split("-")

    # Greedy algorithm: at each step, try to find the longest sequence
    # of parts that forms an existing directory (or the final path component)
    result_parts: list[str] = []
    i = 0

    while i < len(parts):
        found = False
        # Try longest possible component first (most hyphens preserved)
        for j in range(len(parts), i, -1):
            candidate_component = "-".join(parts[i:j])
            candidate_path = "/" + "/".join(result_parts + [candidate_component])

            # For the final component, check if path exists (file or dir)
            # For intermediate components, must be a directory
            if j == len(parts):
                if Path(candidate_path).exists():
                    result_parts.append(candidate_component)
                    i = j
                    found = True
                    break
            else:
                if Path(candidate_path).is_dir():
                    result_parts.append(candidate_component)
                    i = j
                    found = True
                    break

        if not found:
            # No existing path found, use single part and continue
            result_parts.append(parts[i])
            i += 1

    final_path = "/" + "/".join(result_parts)
    return final_path if Path(final_path).exists() else None


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
# Session Markers for JSONL Correlation
# =============================================================================

# Marker format for correlating iTerm sessions with JSONL files
MARKER_PREFIX = "<!claude-team-session:"
MARKER_SUFFIX = "!>"

# iTerm-specific marker for session discovery/recovery
# When running in iTerm, we emit both markers so that orphaned sessions
# can be matched back to their JSONL files even after MCP server restart.
# Future terminal support (e.g., Zed) will use their own marker prefix.
ITERM_MARKER_PREFIX = "<!claude-team-iterm:"
ITERM_MARKER_SUFFIX = "!>"

# Tmux-specific marker for session discovery/recovery
# Tmux pane ids can change across restarts, so we log the pane id in JSONL
# to recover sessions that were started by claude-team.
TMUX_MARKER_PREFIX = "<!claude-team-tmux:"
TMUX_MARKER_SUFFIX = "!>"

# Project path marker for Codex session recovery
PROJECT_MARKER_PREFIX = "<!claude-team-project:"
PROJECT_MARKER_SUFFIX = "!>"


def generate_marker_message(
    session_id: str,
    iterm_session_id: Optional[str] = None,
    tmux_pane_ids: Optional[list[str]] = None,
    project_path: Optional[str] = None,
) -> str:
    """
    Generate a marker message to send to a session for JSONL correlation.

    The marker is used to identify which JSONL file belongs to which
    iTerm session when multiple sessions exist for the same project.

    Args:
        session_id: The managed session ID (e.g., "worker-1")
        iterm_session_id: Optional iTerm2 session ID for discovery/recovery.
            When provided, an additional iTerm-specific marker is emitted.
        tmux_pane_ids: Optional tmux pane IDs for discovery/recovery.
            When provided, tmux-specific markers are emitted for each pane.
        project_path: Optional project path for Codex session recovery.
            When provided, a project marker is emitted.

    Returns:
        A message string to send to the session
    """
    marker_lines = [f"{MARKER_PREFIX}{session_id}{MARKER_SUFFIX}"]

    # Add iTerm-specific marker if provided (for session recovery after MCP restart)
    if iterm_session_id:
        marker_lines.append(
            f"{ITERM_MARKER_PREFIX}{iterm_session_id}{ITERM_MARKER_SUFFIX}"
        )

    if tmux_pane_ids:
        for pane_id in tmux_pane_ids:
            marker_lines.append(f"{TMUX_MARKER_PREFIX}{pane_id}{TMUX_MARKER_SUFFIX}")

    # Add project path marker if provided (used for Codex recovery)
    if project_path:
        marker_lines.append(
            f"{PROJECT_MARKER_PREFIX}{project_path}{PROJECT_MARKER_SUFFIX}"
        )

    marker = "\n".join(marker_lines)

    return (
        f"{marker}\n\n"
        "The above is a marker that assists Claude Teams in locating your session - "
        "respond with ONLY the word 'Identified!' and nothing further. "
        "Please forgive the interruption."
    )


def extract_marker_session_id(text: str) -> Optional[str]:
    """
    Extract a session ID from marker text if present.

    Args:
        text: Text that may contain a marker

    Returns:
        The session ID from the marker, or None if no marker found
    """
    start = text.find(MARKER_PREFIX)
    if start == -1:
        return None
    start += len(MARKER_PREFIX)
    end = text.find(MARKER_SUFFIX, start)
    if end == -1:
        return None
    return text[start:end]


def extract_iterm_session_id(text: str) -> Optional[str]:
    """
    Extract an iTerm session ID from marker text if present.

    Args:
        text: Text that may contain an iTerm marker

    Returns:
        The iTerm session ID from the marker, or None if no marker found
    """
    start = text.find(ITERM_MARKER_PREFIX)
    if start == -1:
        return None
    start += len(ITERM_MARKER_PREFIX)
    end = text.find(ITERM_MARKER_SUFFIX, start)
    if end == -1:
        return None
    return text[start:end]


def extract_project_path(text: str) -> Optional[str]:
    """
    Extract a project path from marker text if present.

    Args:
        text: Text that may contain a project path marker

    Returns:
        The project path from the marker, or None if no marker found
    """
    start = text.find(PROJECT_MARKER_PREFIX)
    if start == -1:
        return None
    start += len(PROJECT_MARKER_PREFIX)
    end = text.find(PROJECT_MARKER_SUFFIX, start)
    if end == -1:
        return None
    return text[start:end]


def extract_tmux_pane_id(text: str) -> Optional[str]:
    """
    Extract a tmux pane ID from marker text if present.

    Args:
        text: Text that may contain a tmux marker

    Returns:
        The tmux pane ID from the marker, or None if no marker found
    """
    start = text.find(TMUX_MARKER_PREFIX)
    if start == -1:
        return None
    start += len(TMUX_MARKER_PREFIX)
    end = text.find(TMUX_MARKER_SUFFIX, start)
    if end == -1:
        return None
    return text[start:end]


def find_jsonl_by_marker(
    project_path: str,
    session_id: str,
    max_age_seconds: int = 120,
) -> Optional[str]:
    """
    Find a JSONL file that contains a specific session marker.

    Scans recent JSONL files in the project directory looking for
    the session marker, which correlates the JSONL to an iTerm session.

    Args:
        project_path: Absolute path to the project
        session_id: The session ID to search for in markers
        max_age_seconds: Only check files modified within this many seconds

    Returns:
        The Claude session ID (JSONL filename stem) if found, None otherwise
    """
    project_dir = get_project_dir(project_path)
    if not project_dir.exists():
        return None

    marker = f"{MARKER_PREFIX}{session_id}{MARKER_SUFFIX}"
    now = time.time()

    # Check recent JSONL files
    for f in project_dir.glob("*.jsonl"):
        # Skip agent files
        if f.name.startswith("agent-"):
            continue

        # Skip old files
        if now - f.stat().st_mtime > max_age_seconds:
            continue

        # Search for marker in file (check last portion for efficiency)
        try:
            # Read last 50KB of file (marker should be near the end)
            file_size = f.stat().st_size
            read_size = min(file_size, 50000)
            with open(f, "r") as fp:
                if file_size > read_size:
                    fp.seek(file_size - read_size)
                content = fp.read()

            if marker in content:
                return f.stem
        except Exception:
            continue

    return None


@dataclass
class ItermSessionMatch:
    """Result of matching an iTerm session ID to a JSONL file."""

    iterm_session_id: str
    internal_session_id: str  # Our claude-team session ID
    jsonl_path: Path
    project_path: str  # Recovered from directory slug


@dataclass
class TmuxSessionMatch:
    """Result of matching a tmux pane ID to a JSONL file."""

    tmux_pane_id: str
    internal_session_id: str  # Our claude-team session ID
    jsonl_path: Path
    project_path: str  # Recovered from directory slug


@dataclass
class CodexSessionMatch:
    """Result of matching a Codex session marker to a JSONL file."""

    iterm_session_id: Optional[str]
    internal_session_id: str
    jsonl_path: Path
    project_path: str


# Helper to iterate recent Codex session files for marker scans.
def _iter_recent_codex_session_files(max_age_seconds: int) -> list[Path]:
    now = time.time()
    cutoff = now - max_age_seconds
    recent_dirs: list[Path] = []

    # Walk newest date directories first (limit to a few days to avoid scanning too much).
    if not CODEX_SESSIONS_DIR.exists():
        return []

    # Build a short list of recent day directories (YYYY/MM/DD) to scan.
    for year_dir in sorted(CODEX_SESSIONS_DIR.iterdir(), reverse=True):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir(), reverse=True):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir(), reverse=True):
                if not day_dir.is_dir():
                    continue
                recent_dirs.append(day_dir)
                if len(recent_dirs) >= 3:
                    break
            if len(recent_dirs) >= 3:
                break
        if len(recent_dirs) >= 3:
            break

    candidates: list[Path] = []

    # Collect JSONL files in the recent directories, filtering by age.
    for day_dir in recent_dirs:
        for jsonl_file in day_dir.glob("rollout-*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            candidates.append(jsonl_file)

    return candidates


# Helper to scan a Codex JSONL file for our markers.
def _scan_codex_markers(
    jsonl_path: Path,
    *,
    iterm_session_id: Optional[str] = None,
    internal_session_id: Optional[str] = None,
    tmux_pane_id: Optional[str] = None,
) -> Optional[CodexSessionMatch]:
    try:
        with open(jsonl_path, "r") as fp:
            # Scan line-by-line so we can short-circuit as soon as markers are found.
            for line in fp:
                if (
                    MARKER_PREFIX not in line
                    and ITERM_MARKER_PREFIX not in line
                    and TMUX_MARKER_PREFIX not in line
                    and PROJECT_MARKER_PREFIX not in line
                ):
                    continue

                # Extract markers directly from the JSON line string (no full JSON parse).
                found_internal = extract_marker_session_id(line)
                found_iterm = extract_iterm_session_id(line)
                found_tmux = extract_tmux_pane_id(line)
                found_project = extract_project_path(line)

                # Enforce target filters if provided.
                if internal_session_id and found_internal != internal_session_id:
                    continue
                if iterm_session_id and found_iterm != iterm_session_id:
                    continue
                if tmux_pane_id and found_tmux != tmux_pane_id:
                    continue

                # Require both internal ID and project path for a valid match.
                if found_internal and found_project:
                    return CodexSessionMatch(
                        iterm_session_id=found_iterm,
                        internal_session_id=found_internal,
                        jsonl_path=jsonl_path,
                        project_path=found_project,
                    )
    except OSError:
        return None

    return None


def find_codex_session_by_iterm_id(
    iterm_session_id: str,
    max_age_seconds: int = 3600,
) -> Optional[CodexSessionMatch]:
    """
    Find a Codex session file containing a specific iTerm session marker.

    Scans recent Codex session files for our markers and returns the
    first match that includes the iTerm session ID.

    Args:
        iterm_session_id: The iTerm2 session ID to search for
        max_age_seconds: Only check files modified within this many seconds

    Returns:
        CodexSessionMatch with recovery info, or None if not found
    """
    for jsonl_path in _iter_recent_codex_session_files(max_age_seconds):
        match = _scan_codex_markers(
            jsonl_path,
            iterm_session_id=iterm_session_id,
        )
        if match:
            return match
    return None


def find_codex_session_by_tmux_id(
    tmux_pane_id: str,
    max_age_seconds: int = 3600,
) -> Optional[CodexSessionMatch]:
    """
    Find a Codex session file containing a specific tmux pane marker.

    Scans recent Codex session files for our markers and returns the
    first match that includes the tmux pane ID.

    Args:
        tmux_pane_id: The tmux pane ID to search for
        max_age_seconds: Only check files modified within this many seconds

    Returns:
        CodexSessionMatch with recovery info, or None if not found
    """
    for jsonl_path in _iter_recent_codex_session_files(max_age_seconds):
        match = _scan_codex_markers(
            jsonl_path,
            tmux_pane_id=tmux_pane_id,
        )
        if match:
            return match
    return None


def find_codex_session_by_internal_id(
    session_id: str,
    max_age_seconds: int = 3600,
) -> Optional[CodexSessionMatch]:
    """
    Find a Codex session file containing a specific internal session marker.

    Scans recent Codex session files for our internal session marker and
    returns the first matching file.

    Args:
        session_id: The internal session ID to search for
        max_age_seconds: Only check files modified within this many seconds

    Returns:
        CodexSessionMatch with recovery info, or None if not found
    """
    for jsonl_path in _iter_recent_codex_session_files(max_age_seconds):
        match = _scan_codex_markers(
            jsonl_path,
            internal_session_id=session_id,
        )
        if match:
            return match
    return None


def find_jsonl_by_iterm_id(
    iterm_session_id: str,
    max_age_seconds: int = 3600,
) -> Optional[ItermSessionMatch]:
    """
    Find a JSONL file containing a specific iTerm session marker.

    Scans all project directories in ~/.claude/projects/ for JOSNLs
    that contain the iTerm-specific marker. This enables session recovery
    after MCP server restart.

    Only looks at root user messages (type="user", parentUuid=null) and
    extracts markers from the message.content field for reliability.

    Args:
        iterm_session_id: The iTerm2 session ID to search for
        max_age_seconds: Only check files modified within this many seconds

    Returns:
        ItermSessionMatch with full recovery info, or None if not found
    """
    iterm_marker = f"{ITERM_MARKER_PREFIX}{iterm_session_id}{ITERM_MARKER_SUFFIX}"
    now = time.time()

    # Scan all project directories
    if not CLAUDE_PROJECTS_DIR.exists():
        return None

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # Check JSONL files in this project
        for f in project_dir.glob("*.jsonl"):
            # Skip agent files
            if f.name.startswith("agent-"):
                continue

            # Skip old files
            try:
                if now - f.stat().st_mtime > max_age_seconds:
                    continue
            except OSError:
                continue

            # Parse JSONL looking for root user message with our markers
            try:
                with open(f, "r") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # Only look at root user messages (our marker message)
                        if entry.get("type") != "user":
                            continue
                        if entry.get("parentUuid") is not None:
                            continue

                        # Extract message content
                        message = entry.get("message", {})
                        content = message.get("content", "")
                        if not isinstance(content, str):
                            continue

                        # Check for iTerm marker in message content
                        if iterm_marker not in content:
                            continue

                        # Extract internal session ID from the same content
                        internal_id = extract_marker_session_id(content)
                        if not internal_id:
                            continue

                        # Recover project path from directory slug
                        project_path = unslugify_path(project_dir.name)
                        if not project_path:
                            continue

                        return ItermSessionMatch(
                            iterm_session_id=iterm_session_id,
                            internal_session_id=internal_id,
                            jsonl_path=f,
                            project_path=project_path,
                        )

            except Exception:
                continue

    return None


def find_jsonl_by_tmux_id(
    tmux_pane_id: str,
    max_age_seconds: int = 3600,
) -> Optional[TmuxSessionMatch]:
    """
    Find a JSONL file containing a specific tmux pane marker.

    Scans all project directories in ~/.claude/projects/ for JSONLs
    that contain the tmux-specific marker. This enables session recovery
    after MCP server restart.

    Only looks at root user messages (type="user", parentUuid=null) and
    extracts markers from the message.content field for reliability.

    Args:
        tmux_pane_id: The tmux pane ID to search for
        max_age_seconds: Only check files modified within this many seconds

    Returns:
        TmuxSessionMatch with full recovery info, or None if not found
    """
    tmux_marker = f"{TMUX_MARKER_PREFIX}{tmux_pane_id}{TMUX_MARKER_SUFFIX}"
    now = time.time()

    # Scan all project directories
    if not CLAUDE_PROJECTS_DIR.exists():
        return None

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # Check JSONL files in this project
        for f in project_dir.glob("*.jsonl"):
            # Skip agent files
            if f.name.startswith("agent-"):
                continue

            # Skip old files
            try:
                if now - f.stat().st_mtime > max_age_seconds:
                    continue
            except OSError:
                continue

            # Parse JSONL looking for root user message with our markers
            try:
                with open(f, "r") as fp:
                    for line in fp:
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # Only look at root user messages (our marker message)
                        if entry.get("type") != "user":
                            continue
                        if entry.get("parentUuid") is not None:
                            continue

                        # Extract message content
                        message = entry.get("message", {})
                        content = message.get("content", "")
                        if not isinstance(content, str):
                            continue

                        # Check for tmux marker in message content
                        if tmux_marker not in content:
                            continue

                        # Extract internal session ID from the same content
                        internal_id = extract_marker_session_id(content)
                        if not internal_id:
                            continue

                        # Recover project path from directory slug
                        project_path = unslugify_path(project_dir.name)
                        if not project_path:
                            continue

                        return TmuxSessionMatch(
                            tmux_pane_id=tmux_pane_id,
                            internal_session_id=internal_id,
                            jsonl_path=f,
                            project_path=project_path,
                        )

            except Exception:
                continue

    return None


async def await_marker_in_jsonl(
    project_path: str,
    session_id: str,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> Optional[str]:
    """
    Poll for a session marker to appear in the JSONL.

    The marker is logged as a user message the instant send_prompt() returns.
    This function polls immediately (no initial delay) and returns as soon as
    the marker is found.

    Args:
        project_path: Absolute path to the project
        session_id: The session ID to search for in markers
        timeout: Maximum seconds to wait (default 30)
        poll_interval: Seconds between polls (default 0.1)

    Returns:
        The Claude session ID (JSONL filename stem) if found, None on timeout
    """
    import asyncio

    start = time.time()

    while time.time() - start < timeout:
        result = find_jsonl_by_marker(project_path, session_id)
        if result:
            return result
        await asyncio.sleep(poll_interval)

    return None


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

            # Extract text content, tool uses, and thinking blocks
            if isinstance(raw_content, str):
                text_content = raw_content
                tool_uses = []
                thinking_content = None
            else:
                text_parts = []
                tool_uses = []
                thinking_parts = []
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
                        elif item.get("type") == "thinking":
                            thinking_parts.append(item.get("thinking", ""))
                text_content = "\n".join(text_parts)
                thinking_content = "\n".join(thinking_parts) if thinking_parts else None

            ts = parse_timestamp(entry)

            messages.append(
                Message(
                    uuid=entry.get("uuid", ""),
                    parent_uuid=entry.get("parentUuid"),
                    role=role,
                    content=text_content,
                    timestamp=ts,
                    tool_uses=tool_uses,
                    thinking=thinking_content,
                )
            )

    return SessionState(
        session_id=session_id,
        project_path=project_path,
        jsonl_path=jsonl_path,
        messages=messages,
        last_modified=jsonl_path.stat().st_mtime if jsonl_path.exists() else 0,
    )


# =============================================================================
# Codex Session Parsing
# =============================================================================


def parse_codex_session(jsonl_path: Path) -> SessionState:
    """
    Parse a Codex session JSONL file into a SessionState object.

    Codex has a different JSONL format than Claude Code:
    - Interactive mode uses event_msg and response_item wrappers
    - Exec mode uses direct ThreadEvent types (item.completed, etc.)

    Args:
        jsonl_path: Path to the Codex JSONL file

    Returns:
        Parsed SessionState object with messages extracted
    """
    messages = []
    session_id = jsonl_path.stem

    try:
        with open(jsonl_path, "r") as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = _parse_codex_event(data, line_num)
                if msg:
                    messages.append(msg)

    except FileNotFoundError:
        pass

    return SessionState(
        session_id=session_id,
        project_path="",  # Codex doesn't have project path in the same way
        jsonl_path=jsonl_path,
        messages=messages,
        last_modified=jsonl_path.stat().st_mtime if jsonl_path.exists() else 0,
    )


def _parse_codex_event(data: dict, line_num: int) -> Optional[Message]:
    """
    Parse a single Codex JSONL event into a Message if applicable.

    Handles both interactive mode format (wrapped events) and exec mode format
    (direct ThreadEvent types).

    Args:
        data: Parsed JSON dict from JSONL line
        line_num: Line number for UUID generation

    Returns:
        Message object if this event represents a message, None otherwise
    """
    event_type = data.get("type", "")
    now = datetime.now()

    # Interactive mode: event_msg wrapper
    if event_type == "event_msg":
        payload = data.get("payload", {})
        payload_type = payload.get("type")

        if payload_type == "agent_message":
            # Agent response message
            text = payload.get("text", "")
            if text:
                return Message(
                    uuid=payload.get("id", f"codex-{line_num}"),
                    parent_uuid=None,
                    role="assistant",
                    content=text,
                    timestamp=now,
                )

        elif payload_type == "user_message":
            # User input message
            text = payload.get("text", "")
            if text:
                return Message(
                    uuid=payload.get("id", f"codex-user-{line_num}"),
                    parent_uuid=None,
                    role="user",
                    content=text,
                    timestamp=now,
                )

    # Interactive mode: response_item wrapper
    elif event_type == "response_item":
        payload = data.get("payload", {})
        payload_type = payload.get("type")
        role = payload.get("role", "")

        if payload_type == "message":
            # Extract content from the message
            content_list = payload.get("content", [])
            text_parts = []
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "output_text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, dict) and item.get("type") == "input_text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))

            text = "".join(text_parts)
            if text:
                return Message(
                    uuid=payload.get("id", f"codex-resp-{line_num}"),
                    parent_uuid=None,
                    role=role if role else "assistant",
                    content=text,
                    timestamp=now,
                )

        elif payload_type == "agent_message":
            # Direct agent_message in payload
            text = payload.get("text", "")
            if text:
                return Message(
                    uuid=payload.get("id", f"codex-agent-{line_num}"),
                    parent_uuid=None,
                    role="assistant",
                    content=text,
                    timestamp=now,
                )

    # Exec mode: item.completed events
    elif event_type == "item.completed":
        item = data.get("item", {})
        item_type = item.get("type")

        if item_type == "agent_message":
            text = item.get("text", "")
            if text:
                return Message(
                    uuid=item.get("id", f"codex-exec-{line_num}"),
                    parent_uuid=None,
                    role="assistant",
                    content=text,
                    timestamp=now,
                )

        elif item_type == "reasoning":
            # Reasoning/thinking block
            text = item.get("text", "")
            if text:
                return Message(
                    uuid=item.get("id", f"codex-think-{line_num}"),
                    parent_uuid=None,
                    role="assistant",
                    content="",  # Put reasoning in thinking field instead
                    timestamp=now,
                    thinking=text,
                )

        elif item_type == "command_execution":
            # Shell command execution
            cmd = item.get("command", "")
            output = item.get("aggregated_output", "")
            exit_code = item.get("exit_code")
            status = item.get("status", "")
            if cmd:
                content = f"Command: {cmd}\n"
                if output:
                    content += f"Output:\n{output}\n"
                if exit_code is not None:
                    content += f"Exit code: {exit_code}"
                return Message(
                    uuid=item.get("id", f"codex-cmd-{line_num}"),
                    parent_uuid=None,
                    role="assistant",
                    content=content,
                    timestamp=now,
                    tool_uses=[{
                        "name": "command_execution",
                        "input": {"command": cmd, "status": status},
                    }],
                )

        elif item_type == "file_change":
            # File modification
            changes = item.get("changes", [])
            if changes:
                change_lines = []
                for c in changes:
                    path = c.get("path", "")
                    kind = c.get("kind", "")
                    change_lines.append(f"  {kind}: {path}")
                content = "File changes:\n" + "\n".join(change_lines)
                return Message(
                    uuid=item.get("id", f"codex-file-{line_num}"),
                    parent_uuid=None,
                    role="assistant",
                    content=content,
                    timestamp=now,
                    tool_uses=[{
                        "name": "file_change",
                        "input": {"changes": changes},
                    }],
                )

    return None


# =============================================================================
# Stop Hook Detection
# =============================================================================

# Marker format for Stop hook completion detection
STOP_HOOK_MARKER_PREFIX = "[worker-done:"
STOP_HOOK_MARKER_SUFFIX = "]"


@dataclass
class StopHookEntry:
    """A stop_hook_summary entry from the JSONL."""
    timestamp: datetime
    marker_id: Optional[str]  # The session ID from the marker, if found
    hook_count: int
    commands: list[str]  # The hook commands that ran


def extract_stop_hook_marker(command: str) -> Optional[str]:
    """
    Extract the marker ID from a Stop hook command.

    The marker format is: echo [worker-done:SESSION_ID]

    Args:
        command: The hook command string

    Returns:
        The session/marker ID if found, None otherwise
    """
    start = command.find(STOP_HOOK_MARKER_PREFIX)
    if start == -1:
        return None
    start += len(STOP_HOOK_MARKER_PREFIX)
    end = command.find(STOP_HOOK_MARKER_SUFFIX, start)
    if end == -1:
        return None
    return command[start:end]


def parse_stop_hook_entries(jsonl_path: Path) -> list[StopHookEntry]:
    """
    Parse all stop_hook_summary entries from a JSONL file.

    Stop hook summaries are logged with:
    - type: "system"
    - subtype: "stop_hook_summary"
    - hookInfos: list of {command: "..."}
    - timestamp: ISO timestamp

    Args:
        jsonl_path: Path to the session JSONL file

    Returns:
        List of StopHookEntry objects, ordered by timestamp
    """
    entries = []

    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Look for stop_hook_summary entries
                if entry.get("type") != "system":
                    continue
                if entry.get("subtype") != "stop_hook_summary":
                    continue

                ts = parse_timestamp(entry)

                # Extract commands from hookInfos
                hook_infos = entry.get("hookInfos", [])
                commands = [h.get("command", "") for h in hook_infos if h.get("command")]

                # Try to find marker in any command
                marker_id = None
                for cmd in commands:
                    marker_id = extract_stop_hook_marker(cmd)
                    if marker_id:
                        break

                entries.append(StopHookEntry(
                    timestamp=ts,
                    marker_id=marker_id,
                    hook_count=entry.get("hookCount", len(commands)),
                    commands=commands,
                ))

    except FileNotFoundError:
        return []

    return sorted(entries, key=lambda e: e.timestamp)


def get_last_stop_hook_for_session(
    jsonl_path: Path,
    session_id: str,
) -> Optional[StopHookEntry]:
    """
    Find the most recent stop_hook_summary entry for a specific session.

    Args:
        jsonl_path: Path to the session JSONL file
        session_id: The session ID to look for in markers

    Returns:
        The most recent StopHookEntry matching the session ID, or None
    """
    entries = parse_stop_hook_entries(jsonl_path)
    for entry in reversed(entries):
        if entry.marker_id == session_id:
            return entry
    return None


def is_session_stopped(
    jsonl_path: Path,
    session_id: str,
) -> bool:
    """
    Check if a session has stopped (completed work) based on Stop hook detection.

    A session is considered stopped if:
    1. There is a stop_hook_summary entry with the session's marker
    2. That entry is the last meaningful entry in the JSONL (no user/assistant
       messages with content exist after it)

    This provides reliable completion detection without relying on idle time
    or explicit TASK_COMPLETE markers.

    Args:
        jsonl_path: Path to the session JSONL file
        session_id: The session ID to check

    Returns:
        True if the session has stopped, False if still working or no data
    """
    # Parse file once, collecting stop hooks and message timestamps
    last_stop_hook_ts: Optional[datetime] = None
    last_message_ts: Optional[datetime] = None

    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Check for stop_hook_summary entries
                if entry.get("type") == "system" and entry.get("subtype") == "stop_hook_summary":
                    # Check if this stop hook matches our session
                    hook_infos = entry.get("hookInfos", [])
                    for h in hook_infos:
                        cmd = h.get("command", "")
                        marker_id = extract_stop_hook_marker(cmd)
                        if marker_id == session_id:
                            ts = parse_timestamp(entry)
                            # Track the latest stop hook for this session
                            if last_stop_hook_ts is None or ts > last_stop_hook_ts:
                                last_stop_hook_ts = ts
                            break
                    continue

                # Check for user/assistant messages with content
                entry_type = entry.get("type", "")
                if entry_type not in ("user", "assistant"):
                    continue

                # Check if this message has actual content
                message = entry.get("message", {})
                content = message.get("content", "")
                if isinstance(content, list):
                    has_text = any(
                        c.get("type") == "text" and c.get("text")
                        for c in content
                        if isinstance(c, dict)
                    )
                    if not has_text:
                        continue
                elif not content:
                    continue

                msg_ts = parse_timestamp(entry)
                # Track the latest message timestamp
                if last_message_ts is None or msg_ts > last_message_ts:
                    last_message_ts = msg_ts

    except FileNotFoundError:
        return False

    # No stop hook found for this session
    if last_stop_hook_ts is None:
        return False

    # Check if any message exists after the stop hook
    if last_message_ts is not None and last_message_ts > last_stop_hook_ts:
        return False

    # Stop hook fired and no messages after it - session is stopped
    return True
