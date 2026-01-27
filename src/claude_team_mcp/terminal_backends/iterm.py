"""
iTerm2 terminal backend adapter.

Wraps iTerm2 session objects in a backend-agnostic interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import TerminalBackend, TerminalSession
from .. import iterm_utils

if TYPE_CHECKING:
    from iterm2.app import App as ItermApp
    from iterm2.connection import Connection as ItermConnection
    from iterm2.profile import LocalWriteOnlyProfile as ItermLocalWriteOnlyProfile
    from iterm2.session import Session as ItermSession


class ItermBackend(TerminalBackend):
    """Terminal backend adapter for iTerm2."""

    backend_id = "iterm"

    def __init__(self, connection: "ItermConnection", app: "ItermApp") -> None:
        """Initialize the backend with an active iTerm2 connection and app."""
        self._connection = connection
        self._app = app

    @property
    def connection(self) -> "ItermConnection":
        """Return the active iTerm2 connection."""
        return self._connection

    @property
    def app(self) -> "ItermApp":
        """Return the active iTerm2 app handle."""
        return self._app

    def wrap_session(self, handle: "ItermSession") -> TerminalSession:
        """Wrap an iTerm2 session handle in a TerminalSession."""
        return TerminalSession(
            backend_id=self.backend_id,
            native_id=handle.session_id,
            handle=handle,
        )

    def unwrap_session(self, session: TerminalSession) -> "ItermSession":
        """Extract the iTerm2 session handle from a TerminalSession."""
        return session.handle

    async def create_session(
        self,
        name: str | None = None,
        *,
        profile: str | None = None,
        profile_customizations: "ItermLocalWriteOnlyProfile" | None = None,
    ) -> TerminalSession:
        """Create a new iTerm2 window/session and return its initial pane."""
        window = await iterm_utils.create_window(
            self._connection,
            profile=profile,
            profile_customizations=profile_customizations,
        )
        tab = window.current_tab
        if tab is None or tab.current_session is None:
            raise RuntimeError("Failed to get initial iTerm2 session from window")
        if name:
            try:
                await tab.async_set_title(name)
            except Exception:
                pass
        return self.wrap_session(tab.current_session)

    async def send_text(self, session: TerminalSession, text: str) -> None:
        """Send raw text to an iTerm2 session."""
        await iterm_utils.send_text(self.unwrap_session(session), text)

    async def send_key(self, session: TerminalSession, key: str) -> None:
        """Send a special key to an iTerm2 session."""
        await iterm_utils.send_key(self.unwrap_session(session), key)

    async def read_screen_text(self, session: TerminalSession) -> str:
        """Read visible screen content from an iTerm2 session."""
        return await iterm_utils.read_screen_text(self.unwrap_session(session))

    async def split_pane(
        self,
        session: TerminalSession,
        *,
        vertical: bool = True,
        before: bool = False,
        profile: str | None = None,
        profile_customizations: "ItermLocalWriteOnlyProfile" | None = None,
    ) -> TerminalSession:
        """Split an iTerm2 session pane and return the new pane."""
        new_session = await iterm_utils.split_pane(
            self.unwrap_session(session),
            vertical=vertical,
            before=before,
            profile=profile,
            profile_customizations=profile_customizations,
        )
        return self.wrap_session(new_session)

    async def close_session(self, session: TerminalSession, force: bool = False) -> None:
        """Close an iTerm2 session pane."""
        await iterm_utils.close_pane(self.unwrap_session(session), force=force)

    async def create_multi_pane_layout(
        self,
        layout: str,
        *,
        profile: str | None = None,
        profile_customizations: dict[str, Any] | None = None,
    ) -> dict[str, TerminalSession]:
        """Create an iTerm2 multi-pane layout and wrap panes as TerminalSessions."""
        panes = await iterm_utils.create_multi_pane_layout(
            self._connection,
            layout,
            profile=profile,
            profile_customizations=profile_customizations,
        )
        return {name: self.wrap_session(session) for name, session in panes.items()}

    async def list_sessions(self) -> list[TerminalSession]:
        """List all iTerm2 sessions across all windows and tabs."""
        sessions: list[TerminalSession] = []
        for window in self._app.terminal_windows:
            for tab in window.tabs:
                for iterm_session in tab.sessions:
                    sessions.append(self.wrap_session(iterm_session))
        return sessions
