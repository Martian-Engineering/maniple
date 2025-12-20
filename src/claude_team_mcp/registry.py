"""
Session Registry for Claude Team MCP

Tracks all spawned Claude Code sessions, maintaining the mapping between
our session IDs, iTerm2 session objects, and Claude JSONL session IDs.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .session_state import find_active_session, get_project_dir, parse_session


@dataclass(frozen=True)
class TerminalId:
    """
    Terminal-agnostic identifier for a session in a terminal emulator.

    Designed for extensibility - same structure works for iTerm, Zed, VS Code, etc.
    After MCP restart, registry is empty but terminal IDs persist. This allows
    tools to accept terminal IDs directly for recovery scenarios.

    Attributes:
        terminal_type: Terminal emulator type ("iterm", "zed", "vscode", etc.)
        native_id: Terminal's native session ID (e.g., iTerm's UUID)
    """

    terminal_type: str
    native_id: str

    def __str__(self) -> str:
        """For display: 'iterm:DB29DB03-...'"""
        return f"{self.terminal_type}:{self.native_id}"

    @classmethod
    def from_string(cls, s: str) -> "TerminalId":
        """
        Parse 'iterm:DB29DB03-...' format.

        Falls back to treating bare IDs as iTerm for backwards compatibility.
        """
        if ":" in s:
            terminal_type, native_id = s.split(":", 1)
            return cls(terminal_type, native_id)
        # Assume bare ID is iTerm for backwards compatibility
        return cls("iterm", s)


class SessionStatus(str, Enum):
    """Status of a managed Claude session."""

    SPAWNING = "spawning"  # Claude is starting up
    READY = "ready"  # Claude is idle, waiting for input
    BUSY = "busy"  # Claude is processing/responding
    CLOSED = "closed"  # Session has been terminated


@dataclass
class ManagedSession:
    """
    Represents a spawned Claude Code session.

    Tracks the iTerm2 session object, project path, and Claude session ID
    discovered from the JSONL file.
    """

    session_id: str  # Our assigned ID (e.g., "worker-1")
    iterm_session: object  # iterm2.Session
    project_path: str
    claude_session_id: Optional[str] = None  # Discovered from JSONL
    name: Optional[str] = None  # Optional friendly name
    status: SessionStatus = SessionStatus.SPAWNING
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    # Coordinator annotations and worktree tracking
    controller_annotation: Optional[str] = None  # Notes from coordinator about assignment
    worktree_path: Optional[Path] = None  # Path to worker's git worktree if any

    # Terminal-agnostic identifier (auto-populated from iterm_session if not set)
    terminal_id: Optional[TerminalId] = None

    def __post_init__(self):
        """Auto-populate terminal_id from iterm_session if not set."""
        if self.terminal_id is None and self.iterm_session is not None:
            # Use object.__setattr__ since we're in __post_init__
            object.__setattr__(
                self,
                "terminal_id",
                TerminalId("iterm", self.iterm_session.session_id),
            )

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP tool responses."""
        return {
            "session_id": self.session_id,
            "terminal_id": str(self.terminal_id) if self.terminal_id else None,
            "terminal_type": self.terminal_id.terminal_type if self.terminal_id else None,
            "native_terminal_id": self.terminal_id.native_id if self.terminal_id else None,
            "name": self.name or self.session_id,
            "project_path": self.project_path,
            "claude_session_id": self.claude_session_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "controller_annotation": self.controller_annotation,
            "worktree_path": str(self.worktree_path) if self.worktree_path else None,
        }

    def update_activity(self) -> None:
        """Update the last_activity timestamp."""
        self.last_activity = datetime.now()

    def discover_claude_session(self) -> Optional[str]:
        """
        Try to discover the Claude session ID from JSONL files.

        Looks for recently modified session files in the project's
        Claude directory. Note: This finds the most recently modified
        JSONL, which may not be correct when multiple sessions exist.
        Prefer discover_claude_session_by_marker() for accurate correlation.

        Returns:
            Session ID if found, None otherwise
        """
        session_id = find_active_session(self.project_path, max_age_seconds=60)
        if session_id:
            self.claude_session_id = session_id
        return session_id

    def discover_claude_session_by_marker(self, max_age_seconds: int = 120) -> Optional[str]:
        """
        Discover the Claude session ID by searching for this session's marker.

        This is more accurate than discover_claude_session() when multiple
        sessions exist for the same project. Requires that a marker message
        was previously sent to the session.

        Args:
            max_age_seconds: Only check JSONL files modified within this time

        Returns:
            Claude session ID if found, None otherwise
        """
        from .session_state import find_jsonl_by_marker

        claude_session_id = find_jsonl_by_marker(
            self.project_path,
            self.session_id,
            max_age_seconds=max_age_seconds,
        )
        if claude_session_id:
            self.claude_session_id = claude_session_id
        return claude_session_id

    def get_jsonl_path(self):
        """
        Get the path to this session's JSONL file.

        Automatically tries to discover the session if not already known.

        Returns:
            Path object, or None if session cannot be discovered
        """
        # Auto-discover if not already known
        if not self.claude_session_id:
            self.discover_claude_session()

        if not self.claude_session_id:
            return None
        return get_project_dir(self.project_path) / f"{self.claude_session_id}.jsonl"

    def get_conversation_state(self):
        """
        Parse and return the current conversation state.

        Returns:
            SessionState object, or None if JSONL not available
        """
        jsonl_path = self.get_jsonl_path()
        if not jsonl_path or not jsonl_path.exists():
            return None
        return parse_session(jsonl_path)


class SessionRegistry:
    """
    Registry for managing Claude Code sessions.

    Maintains a collection of ManagedSession objects and provides
    methods for adding, retrieving, updating, and removing sessions.
    """

    def __init__(self):
        """Initialize an empty registry."""
        self._sessions: dict[str, ManagedSession] = {}

    def _generate_id(self) -> str:
        """Generate a unique session ID as short UUID."""
        return str(uuid.uuid4())[:8]  # e.g., "a3f2b1c9"

    def add(
        self,
        iterm_session: object,
        project_path: str,
        name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ManagedSession:
        """
        Add a new session to the registry.

        Args:
            iterm_session: iTerm2 session object
            project_path: Directory where Claude is running
            name: Optional friendly name
            session_id: Optional specific ID (auto-generated if not provided)

        Returns:
            The created ManagedSession
        """
        if session_id is None:
            session_id = self._generate_id()

        session = ManagedSession(
            session_id=session_id,
            iterm_session=iterm_session,
            project_path=project_path,
            name=name,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[ManagedSession]:
        """
        Get a session by ID.

        Args:
            session_id: The session ID to look up

        Returns:
            ManagedSession if found, None otherwise
        """
        return self._sessions.get(session_id)

    def get_by_name(self, name: str) -> Optional[ManagedSession]:
        """
        Get a session by its friendly name.

        Args:
            name: The session name to look up

        Returns:
            ManagedSession if found, None otherwise
        """
        for session in self._sessions.values():
            if session.name == name:
                return session
        return None

    def resolve(self, identifier: str) -> Optional[ManagedSession]:
        """
        Resolve a session by any known identifier.

        Lookup order (most specific first):
        1. Internal session_id (e.g., "d875b833")
        2. Terminal native ID (e.g., "DB29DB03-AA52-4FBF-879A-4DA2C5F9F823")
        3. Session name

        After MCP restart, internal IDs are lost until import. This method
        allows tools to accept terminal IDs directly for recovery scenarios.

        Args:
            identifier: Any session identifier (internal ID, terminal ID, or name)

        Returns:
            ManagedSession if found, None otherwise
        """
        # 1. Try internal session_id (fast dict lookup)
        if identifier in self._sessions:
            return self._sessions[identifier]

        # 2. Try terminal native ID (iterate once)
        for session in self._sessions.values():
            if session.terminal_id and session.terminal_id.native_id == identifier:
                return session

        # 3. Try name (last resort)
        return self.get_by_name(identifier)

    def list_all(self) -> list[ManagedSession]:
        """
        Get all registered sessions.

        Returns:
            List of all ManagedSession objects
        """
        return list(self._sessions.values())

    def list_by_status(self, status: SessionStatus) -> list[ManagedSession]:
        """
        Get sessions filtered by status.

        Args:
            status: Status to filter by

        Returns:
            List of matching ManagedSession objects
        """
        return [s for s in self._sessions.values() if s.status == status]

    def remove(self, session_id: str) -> Optional[ManagedSession]:
        """
        Remove a session from the registry.

        Args:
            session_id: ID of session to remove

        Returns:
            The removed session, or None if not found
        """
        return self._sessions.pop(session_id, None)

    def update_status(self, session_id: str, status: SessionStatus) -> bool:
        """
        Update a session's status.

        Args:
            session_id: ID of session to update
            status: New status

        Returns:
            True if session was found and updated
        """
        session = self._sessions.get(session_id)
        if session:
            session.status = status
            session.update_activity()
            return True
        return False

    def count(self) -> int:
        """Return the number of registered sessions."""
        return len(self._sessions)

    def count_by_status(self, status: SessionStatus) -> int:
        """Return the count of sessions with a specific status."""
        return len(self.list_by_status(status))

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions
