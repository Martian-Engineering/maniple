"""
iTerm2 terminal backend adapter.

Wraps iTerm2 session objects in a backend-agnostic interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .base import TerminalBackend, TerminalSession
from .. import iterm_utils

if TYPE_CHECKING:
    from iterm2.app import App as ItermApp
    from iterm2.connection import Connection as ItermConnection
    from iterm2.profile import LocalWriteOnlyProfile as ItermLocalWriteOnlyProfile
    from iterm2.session import Session as ItermSession
    from iterm2.tab import Tab as ItermTab
    from iterm2.window import Window as ItermWindow

    from ..cli_backends import AgentCLI

# Re-export iTerm-specific layout limit via the backend layer.
MAX_PANES_PER_TAB = iterm_utils.MAX_PANES_PER_TAB


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

    def handle_from_session(self, session: "ItermSession") -> TerminalSession:
        """Wrap a native iTerm2 session in a TerminalSession (alias for wrap_session)."""
        return self.wrap_session(session)

    async def find_handle_by_native_id(self, native_id: str) -> Optional[TerminalSession]:
        """
        Find a TerminalSession for a native iTerm2 session ID.

        Returns None if the session cannot be found.
        """
        for window in self._app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id == native_id:
                        return self.wrap_session(session)
        return None

    def list_handles(self) -> list[TerminalSession]:
        """Return TerminalSessions for all iTerm2 sessions in all windows."""
        handles: list[TerminalSession] = []
        for window in self._app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    handles.append(self.wrap_session(session))
        return handles

    async def create_session(
        self,
        name: str | None = None,
        *,
        project_path: str | None = None,
        issue_id: str | None = None,
        coordinator_annotation: str | None = None,
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

    async def send_prompt(
        self, session: TerminalSession, text: str, submit: bool = True
    ) -> None:
        """Send a prompt to a terminal session, optionally submitting it."""
        await iterm_utils.send_prompt(self.unwrap_session(session), text, submit=submit)

    async def send_prompt_for_agent(
        self,
        session: TerminalSession,
        text: str,
        agent_type: str = "claude",
        submit: bool = True,
    ) -> None:
        """Send a prompt with agent-specific handling (Claude vs Codex)."""
        await iterm_utils.send_prompt_for_agent(
            self.unwrap_session(session),
            text,
            agent_type=agent_type,
            submit=submit,
        )

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
        return self.list_handles()

    async def start_agent_in_session(
        self,
        handle: TerminalSession,
        cli: "AgentCLI",
        project_path: str,
        dangerously_skip_permissions: bool = False,
        env: Optional[dict[str, str]] = None,
        shell_ready_timeout: float = 10.0,
        agent_ready_timeout: float = 30.0,
        stop_hook_marker_id: Optional[str] = None,
        output_capture_path: Optional[str] = None,
    ) -> None:
        """Start a CLI agent in an existing terminal session."""
        await iterm_utils.start_agent_in_session(
            session=self.unwrap_session(handle),
            cli=cli,
            project_path=project_path,
            dangerously_skip_permissions=dangerously_skip_permissions,
            env=env,
            shell_ready_timeout=shell_ready_timeout,
            agent_ready_timeout=agent_ready_timeout,
            stop_hook_marker_id=stop_hook_marker_id,
            output_capture_path=output_capture_path,
        )

    async def find_available_window(
        self,
        max_panes: int = MAX_PANES_PER_TAB,
        managed_session_ids: Optional[set[str]] = None,
    ) -> Optional[tuple["ItermWindow", "ItermTab", TerminalSession]]:
        """Find a window/tab with space for more panes."""
        result = await iterm_utils.find_available_window(
            self._app,
            max_panes=max_panes,
            managed_session_ids=managed_session_ids,
        )
        if not result:
            return None
        window, tab, session = result
        return window, tab, self.wrap_session(session)

    async def get_window_for_handle(
        self,
        handle: TerminalSession,
    ) -> Optional["ItermWindow"]:
        """Return the window containing the given terminal session."""
        return await iterm_utils.get_window_for_session(
            self._app, self.unwrap_session(handle)
        )

    async def activate_app(self) -> None:
        """Bring the terminal application to the foreground."""
        await self._app.async_activate()

    async def activate_window_for_handle(self, handle: TerminalSession) -> None:
        """Activate the window containing the given terminal session."""
        native_session = self.unwrap_session(handle)
        tab = native_session.tab
        if tab is None:
            return
        window = tab.window
        if window is None:
            return
        await window.async_activate()
