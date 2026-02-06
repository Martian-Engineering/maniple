"""
Terminal backend abstractions for Claude Team MCP.

Defines the backend protocol and a backend-agnostic session handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TerminalSession:
    """
    Backend-agnostic handle to a terminal session or pane.

    Attributes:
        backend_id: Identifier for the backend ("iterm", "tmux", etc.)
        native_id: Backend-native session or pane id
        handle: Backend-specific handle object (if any)
        metadata: Optional backend-specific metadata
    """

    backend_id: str
    native_id: str
    handle: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TerminalBackend(Protocol):
    """
    Protocol for terminal backend implementations.

    Backends should provide thin adapters over their native APIs so
    claude-team can manage sessions without hard-coding terminals.
    """

    @property
    def backend_id(self) -> str:
        """Return a stable backend identifier ("iterm", "tmux", etc.)."""
        ...

    def wrap_session(self, handle: Any) -> TerminalSession:
        """Wrap a backend-native handle in a TerminalSession."""
        ...

    def unwrap_session(self, session: TerminalSession) -> Any:
        """Extract the backend-native handle from a TerminalSession."""
        ...

    async def create_session(
        self,
        name: str | None = None,
        *,
        project_path: str | None = None,
        issue_id: str | None = None,
        coordinator_annotation: str | None = None,
        profile: str | None = None,
        profile_customizations: Any | None = None,
    ) -> TerminalSession:
        """Create a new terminal session/pane and return it."""
        ...

    async def send_text(self, session: TerminalSession, text: str) -> None:
        """Send raw text to the terminal session."""
        ...

    async def send_key(self, session: TerminalSession, key: str) -> None:
        """Send a special key (enter, ctrl-c, etc.) to the session."""
        ...

    async def read_screen_text(self, session: TerminalSession) -> str:
        """Read visible screen content as text."""
        ...

    async def split_pane(
        self,
        session: TerminalSession,
        *,
        vertical: bool = True,
        before: bool = False,
        profile: str | None = None,
        profile_customizations: Any | None = None,
    ) -> TerminalSession:
        """Split a session pane and return the new pane."""
        ...

    async def close_session(self, session: TerminalSession, force: bool = False) -> None:
        """Close the session/pane, optionally forcing termination."""
        ...

    async def create_multi_pane_layout(
        self,
        layout: str,
        *,
        profile: str | None = None,
        profile_customizations: dict[str, Any] | None = None,
    ) -> dict[str, TerminalSession]:
        """Create a new multi-pane layout and return pane mapping."""
        ...

    async def list_sessions(self) -> list[TerminalSession]:
        """List all sessions known to the backend."""
        ...
