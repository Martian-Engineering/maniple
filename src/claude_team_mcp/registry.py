"""
Session Registry for Claude Team MCP

Tracks all spawned Claude Code sessions, maintaining the mapping between
our session IDs, terminal session handles, and Claude JSONL session IDs.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from .session_state import (
    find_codex_session_by_internal_id,
    get_project_dir,
    parse_session,
)
from .terminal_backends import TerminalSession

# Type alias for supported agent types
AgentType = Literal["claude", "codex"]


@dataclass(frozen=True)
class TerminalId:
    """
    Terminal-agnostic identifier for a session in a terminal emulator.

    Designed for extensibility - same structure works for iTerm, Zed, VS Code, etc.
    After MCP restart, registry is empty but terminal IDs persist. This allows
    tools to accept terminal IDs directly for recovery scenarios.

    Attributes:
        backend_id: Terminal backend identifier ("iterm", "tmux", "zed", etc.)
        native_id: Terminal's native session ID (e.g., iTerm's UUID)
    """

    backend_id: str
    native_id: str

    def __str__(self) -> str:
        """For display: 'iterm:DB29DB03-...'"""
        return f"{self.backend_id}:{self.native_id}"

    @classmethod
    def from_string(cls, s: str) -> "TerminalId":
        """
        Parse 'iterm:DB29DB03-...' format.

        Falls back to treating bare IDs as iTerm for backwards compatibility.
        """
        if ":" in s:
            backend_id, native_id = s.split(":", 1)
            return cls(backend_id, native_id)
        return cls("iterm", s)


class SessionStatus(str, Enum):
    """Status of a managed Claude session."""

    SPAWNING = "spawning"  # Claude is starting up
    READY = "ready"  # Claude is idle, waiting for input
    BUSY = "busy"  # Claude is processing/responding


@dataclass
class ManagedSession:
    """
    Represents a spawned Claude Code session.

    Tracks terminal session metadata, project path, and Claude session ID
    discovered from the JSONL file.
    """

    session_id: str  # Our assigned ID (e.g., "worker-1")
    terminal_session: TerminalSession
    project_path: str
    claude_session_id: Optional[str] = None  # Discovered from JSONL
    name: Optional[str] = None  # Optional friendly name
    status: SessionStatus = SessionStatus.SPAWNING
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    # Coordinator annotations and worktree tracking
    coordinator_annotation: Optional[str] = None  # Notes from coordinator about assignment
    worktree_path: Optional[Path] = None  # Path to worker's git worktree if any
    main_repo_path: Optional[Path] = None  # Path to main git repo (for worktree cleanup)

    # Terminal-agnostic identifier (auto-populated from terminal_session if not set)
    terminal_id: Optional[TerminalId] = None

    # Agent type: "claude" (default) or "codex"
    agent_type: AgentType = "claude"

    def __post_init__(self):
        """Auto-populate terminal_id from terminal_session if not set."""
        if self.terminal_id is None:
            self.terminal_id = TerminalId(
                self.terminal_session.backend_id,
                self.terminal_session.native_id,
            )

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP tool responses."""
        result = {
            "session_id": self.session_id,
            "terminal_id": str(self.terminal_id) if self.terminal_id else None,
            "name": self.name or self.session_id,
            "project_path": self.project_path,
            "claude_session_id": self.claude_session_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "coordinator_annotation": self.coordinator_annotation,
            "worktree_path": str(self.worktree_path) if self.worktree_path else None,
            "main_repo_path": str(self.main_repo_path) if self.main_repo_path else None,
            "agent_type": self.agent_type,
        }
        return result

    def update_activity(self) -> None:
        """Update the last_activity timestamp."""
        self.last_activity = datetime.now()

    def discover_claude_session_by_marker(self, max_age_seconds: int = 120) -> Optional[str]:
        """
        Discover the Claude session ID by searching for this session's marker.

        Requires that a marker message was previously sent to the session.

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

        For Claude workers: uses marker-based discovery in ~/.claude/projects/.
        For Codex workers: uses marker-based discovery in ~/.codex/sessions/.

        Returns:
            Path object, or None if session cannot be discovered
        """
        if self.agent_type == "codex":
            from .idle_detection import find_codex_session_file

            # Prefer marker-based match, fall back to most recent for legacy sessions.
            match = find_codex_session_by_internal_id(
                self.session_id,
                max_age_seconds=600,
            )
            if match:
                return match.jsonl_path
            return find_codex_session_file(max_age_seconds=600)
        else:
            # For Claude, use marker-based discovery
            # Auto-discover if not already known
            if not self.claude_session_id:
                self.discover_claude_session_by_marker()

            if not self.claude_session_id:
                return None
            return get_project_dir(self.project_path) / f"{self.claude_session_id}.jsonl"

    def get_conversation_state(self):
        """
        Parse and return the current conversation state.

        For Claude workers: uses parse_session() for Claude's JSONL format.
        For Codex workers: uses parse_codex_session() for Codex's JSONL format.

        Returns:
            SessionState object, or None if JSONL not available
        """
        jsonl_path = self.get_jsonl_path()
        if not jsonl_path or not jsonl_path.exists():
            return None

        if self.agent_type == "codex":
            from .session_state import parse_codex_session

            return parse_codex_session(jsonl_path)
        else:
            return parse_session(jsonl_path)

    def is_idle(self) -> bool:
        """
        Check if this session is idle.

        For Claude: Uses stop hook detection - session is idle if its Stop hook
        has fired and no messages have been sent after it.

        For Codex: Searches ~/.codex/sessions/ for the session file and checks
        for agent_message events which indicate the agent finished responding.

        Returns:
            True if idle, False if working or session file not available
        """
        if self.agent_type == "codex":
            from .idle_detection import find_codex_session_file, is_codex_idle

            # Prefer marker-based match, fall back to most recent for legacy sessions.
            match = find_codex_session_by_internal_id(
                self.session_id,
                max_age_seconds=600,
            )
            session_file = match.jsonl_path if match else None
            if not session_file:
                session_file = find_codex_session_file(max_age_seconds=600)
            if not session_file:
                return False
            return is_codex_idle(session_file)
        else:
            # Default: Claude Code with Stop hook detection
            from .idle_detection import is_idle as check_is_idle

            jsonl_path = self.get_jsonl_path()
            if not jsonl_path or not jsonl_path.exists():
                return False
            return check_is_idle(jsonl_path, self.session_id)

    def get_conversation_stats(self) -> dict | None:
        """
        Get conversation statistics for this session.

        Returns:
            Dict with message counts and previews, or None if JSONL not available
        """
        state = self.get_conversation_state()
        if not state:
            return None

        convo = state.conversation
        user_msgs = [m for m in convo if m.role == "user"]
        assistant_msgs = [m for m in convo if m.role == "assistant"]

        return {
            "total_messages": len(convo),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "last_user_prompt": (
                user_msgs[-1].content[:200] + "..."
                if user_msgs and len(user_msgs[-1].content) > 200
                else (user_msgs[-1].content if user_msgs else None)
            ),
            "last_assistant_preview": (
                assistant_msgs[-1].content[:200] + "..."
                if assistant_msgs and len(assistant_msgs[-1].content) > 200
                else (assistant_msgs[-1].content if assistant_msgs else None)
            ),
        }


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
        terminal_session: TerminalSession,
        project_path: str,
        name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ManagedSession:
        """
        Add a new session to the registry.

        Args:
            terminal_session: Backend-agnostic terminal session handle
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
            terminal_session=terminal_session,
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
        2. Terminal ID with backend prefix (e.g., "iterm:DB29DB03-..."),
           or a bare iTerm ID for backwards compatibility
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

        # 2. Try terminal ID (e.g., "iterm:UUID")
        for session in self._sessions.values():
            if session.terminal_id and str(session.terminal_id) == identifier:
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
            session_id: ID of session to remove.
                Accepts internal IDs, terminal IDs, or worker names.

        Returns:
            The removed session, or None if not found
        """
        session = self.resolve(session_id)
        if session:
            return self._sessions.pop(session.session_id, None)
        return None

    def update_status(self, session_id: str, status: SessionStatus) -> bool:
        """
        Update a session's status.

        Args:
            session_id: ID of session to update.
                Accepts internal IDs, terminal IDs, or worker names.
            status: New status

        Returns:
            True if session was found and updated
        """
        session = self.resolve(session_id)
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
