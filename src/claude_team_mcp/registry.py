"""
Session Registry for Claude Team MCP

Tracks all spawned Claude Code sessions, maintaining the mapping between
our session IDs, iTerm2 session objects, and Claude JSONL session IDs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .session_state import find_active_session, get_project_dir, parse_session


class SessionStatus(str, Enum):
    """Status of a managed Claude session."""

    SPAWNING = "spawning"  # Claude is starting up
    READY = "ready"  # Claude is idle, waiting for input
    BUSY = "busy"  # Claude is processing/responding
    CLOSED = "closed"  # Session has been terminated


@dataclass
class TaskInfo:
    """
    Information about a delegated task.

    Tracks the task that was sent to a session, including the baseline
    state when the task was delegated.
    """

    task_id: str  # Unique task identifier
    description: str  # Task description/prompt sent
    started_at: datetime = field(default_factory=datetime.now)
    baseline_message_uuid: Optional[str] = None  # Last message UUID before task
    beads_issue_id: Optional[str] = None  # Optional linked beads issue

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP tool responses."""
        return {
            "task_id": self.task_id,
            "description": self.description[:200] + "..."
            if len(self.description) > 200
            else self.description,
            "started_at": self.started_at.isoformat(),
            "baseline_message_uuid": self.baseline_message_uuid,
            "beads_issue_id": self.beads_issue_id,
        }


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
    current_task: Optional[TaskInfo] = None  # Currently delegated task
    task_history: list[TaskInfo] = field(default_factory=list)  # Completed tasks

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP tool responses."""
        result = {
            "session_id": self.session_id,
            "name": self.name or self.session_id,
            "project_path": self.project_path,
            "claude_session_id": self.claude_session_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "has_active_task": self.current_task is not None,
        }
        if self.current_task:
            result["current_task"] = self.current_task.to_dict()
        return result

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

    def start_task(
        self,
        task_id: str,
        description: str,
        beads_issue_id: Optional[str] = None,
    ) -> TaskInfo:
        """
        Start tracking a new delegated task.

        Captures the baseline message UUID for completion detection.

        Args:
            task_id: Unique identifier for this task
            description: Task description/prompt
            beads_issue_id: Optional linked beads issue

        Returns:
            The created TaskInfo
        """
        # Get baseline message UUID
        baseline_uuid = None
        state = self.get_conversation_state()
        if state and state.last_assistant_message:
            baseline_uuid = state.last_assistant_message.uuid

        # Create task info
        task = TaskInfo(
            task_id=task_id,
            description=description,
            baseline_message_uuid=baseline_uuid,
            beads_issue_id=beads_issue_id,
        )

        # Archive current task if exists
        if self.current_task:
            self.task_history.append(self.current_task)

        self.current_task = task
        self.update_activity()
        return task

    def complete_task(self) -> Optional[TaskInfo]:
        """
        Mark current task as complete and archive it.

        Returns:
            The completed TaskInfo, or None if no active task
        """
        if not self.current_task:
            return None

        completed = self.current_task
        self.task_history.append(completed)
        self.current_task = None
        self.update_activity()
        return completed


class SessionRegistry:
    """
    Registry for managing Claude Code sessions.

    Maintains a collection of ManagedSession objects and provides
    methods for adding, retrieving, updating, and removing sessions.
    """

    def __init__(self):
        """Initialize an empty registry."""
        self._sessions: dict[str, ManagedSession] = {}
        self._counter: int = 0

    def _generate_id(self, prefix: str = "worker") -> str:
        """Generate a unique session ID."""
        self._counter += 1
        return f"{prefix}-{self._counter}"

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
