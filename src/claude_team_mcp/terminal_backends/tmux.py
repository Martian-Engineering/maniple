"""
Tmux terminal backend adapter.

Provides a TerminalBackend implementation backed by tmux CLI commands.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from typing import Any

from .base import TerminalBackend, TerminalSession


KEY_MAP: dict[str, str] = {
    "enter": "C-m",
    "return": "C-m",
    "newline": "C-j",
    "escape": "Escape",
    "tab": "Tab",
    "backspace": "BSpace",
    "delete": "DC",
    "up": "Up",
    "down": "Down",
    "right": "Right",
    "left": "Left",
    "home": "Home",
    "end": "End",
    "ctrl-c": "C-c",
    "ctrl-d": "C-d",
    "ctrl-u": "C-u",
    "ctrl-l": "C-l",
    "ctrl-z": "C-z",
}

LAYOUT_PANE_NAMES = {
    "single": ["main"],
    "vertical": ["left", "right"],
    "horizontal": ["top", "bottom"],
    "quad": ["top_left", "top_right", "bottom_left", "bottom_right"],
}

LAYOUT_SELECT = {
    "vertical": "even-horizontal",
    "horizontal": "even-vertical",
    "quad": "tiled",
}


class TmuxBackend(TerminalBackend):
    """Terminal backend adapter for tmux."""

    backend_id = "tmux"

    def __init__(self, socket_path: str | None = None) -> None:
        """Initialize the backend with an optional tmux socket path."""
        self._socket_path = socket_path

    def wrap_session(self, handle: Any) -> TerminalSession:
        """Wrap a tmux pane id in a TerminalSession."""
        pane_id = str(handle)
        return TerminalSession(
            backend_id=self.backend_id,
            native_id=pane_id,
            handle=pane_id,
        )

    def unwrap_session(self, session: TerminalSession) -> str:
        """Extract the tmux pane id from a TerminalSession."""
        return str(session.handle)

    async def create_session(
        self,
        name: str | None = None,
        *,
        profile: str | None = None,
        profile_customizations: Any | None = None,
    ) -> TerminalSession:
        """Create a new detached tmux session and return its initial pane."""
        if profile or profile_customizations:
            raise ValueError("tmux backend does not support profiles")

        session_name = name or self._generate_session_name()

        # Create a detached session.
        await self._run_tmux(["new-session", "-d", "-s", session_name])

        # Fetch the initial pane id for the newly created session.
        output = await self._run_tmux(
            ["list-panes", "-t", session_name, "-F", "#{pane_id}"]
        )
        pane_id = self._first_non_empty_line(output)
        if not pane_id:
            raise RuntimeError("Failed to determine tmux pane id for new session")

        return TerminalSession(
            backend_id=self.backend_id,
            native_id=pane_id,
            handle=pane_id,
            metadata={"session_name": session_name},
        )

    async def send_text(self, session: TerminalSession, text: str) -> None:
        """Send raw text to a tmux pane."""
        pane_id = self.unwrap_session(session)
        await self._run_tmux(["send-keys", "-t", pane_id, "-l", text])

    async def send_key(self, session: TerminalSession, key: str) -> None:
        """Send a special key to a tmux pane."""
        pane_id = self.unwrap_session(session)
        tmux_key = KEY_MAP.get(key.lower())
        if tmux_key is None:
            raise ValueError(f"Unknown key: {key}. Available: {list(KEY_MAP.keys())}")
        await self._run_tmux(["send-keys", "-t", pane_id, tmux_key])

    async def read_screen_text(self, session: TerminalSession) -> str:
        """Read visible screen content from a tmux pane."""
        pane_id = self.unwrap_session(session)
        return await self._run_tmux(["capture-pane", "-p", "-t", pane_id])

    async def split_pane(
        self,
        session: TerminalSession,
        *,
        vertical: bool = True,
        before: bool = False,
        profile: str | None = None,
        profile_customizations: Any | None = None,
    ) -> TerminalSession:
        """Split a tmux pane and return the new pane."""
        if profile or profile_customizations:
            raise ValueError("tmux backend does not support profiles")

        pane_id = self.unwrap_session(session)
        args = ["split-window", "-t", pane_id]
        args.append("-h" if vertical else "-v")
        if before:
            args.append("-b")
        # -P prints the new pane id, -F controls the output format.
        args.extend(["-P", "-F", "#{pane_id}"])

        output = await self._run_tmux(args)
        new_pane_id = self._first_non_empty_line(output)
        if not new_pane_id:
            raise RuntimeError("Failed to determine tmux pane id for split")

        metadata = dict(session.metadata) if session.metadata else {}
        return TerminalSession(
            backend_id=self.backend_id,
            native_id=new_pane_id,
            handle=new_pane_id,
            metadata=metadata,
        )

    async def close_session(self, session: TerminalSession, force: bool = False) -> None:
        """Close a tmux pane."""
        pane_id = self.unwrap_session(session)
        _ = force
        await self._run_tmux(["kill-pane", "-t", pane_id])

    async def create_multi_pane_layout(
        self,
        layout: str,
        *,
        profile: str | None = None,
        profile_customizations: dict[str, Any] | None = None,
    ) -> dict[str, TerminalSession]:
        """Create a multi-pane layout in a new tmux session."""
        if profile or profile_customizations:
            raise ValueError("tmux backend does not support profiles")
        if layout not in LAYOUT_PANE_NAMES:
            raise ValueError(f"Unknown layout: {layout}. Valid: {list(LAYOUT_PANE_NAMES.keys())}")

        # Start a new session for this layout.
        initial = await self.create_session()
        session_name = initial.metadata.get("session_name")

        panes: dict[str, TerminalSession] = {}

        if layout == "single":
            panes["main"] = initial
        elif layout == "vertical":
            panes["left"] = initial
            panes["right"] = await self.split_pane(initial, vertical=True)
        elif layout == "horizontal":
            panes["top"] = initial
            panes["bottom"] = await self.split_pane(initial, vertical=False)
        elif layout == "quad":
            panes["top_left"] = initial
            panes["top_right"] = await self.split_pane(initial, vertical=True)
            panes["bottom_left"] = await self.split_pane(initial, vertical=False)
            panes["bottom_right"] = await self.split_pane(panes["top_right"], vertical=False)

        if session_name and layout in LAYOUT_SELECT:
            await self._run_tmux(["select-layout", "-t", session_name, LAYOUT_SELECT[layout]])

        return panes

    async def list_sessions(self) -> list[TerminalSession]:
        """List all tmux panes across sessions."""
        output = await self._run_tmux(
            [
                "list-panes",
                "-a",
                "-F",
                "#{session_name} #{window_index} #{pane_index} #{pane_id}",
            ]
        )

        sessions: list[TerminalSession] = []

        # Each line includes session/window/pane metadata and pane id.
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 4:
                continue
            session_name, window_index, pane_index, pane_id = parts
            sessions.append(
                TerminalSession(
                    backend_id=self.backend_id,
                    native_id=pane_id,
                    handle=pane_id,
                    metadata={
                        "session_name": session_name,
                        "window_index": window_index,
                        "pane_index": pane_index,
                    },
                )
            )

        return sessions

    async def _run_tmux(self, args: list[str]) -> str:
        """Run a tmux command and return stdout."""
        cmd = ["tmux"]
        if self._socket_path:
            cmd.extend(["-S", self._socket_path])
        cmd.extend(args)

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )

        result = await asyncio.to_thread(_run)
        return result.stdout.strip()

    def _generate_session_name(self) -> str:
        """Generate a stable tmux session name for claude-team."""
        return f"claude-team-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _first_non_empty_line(text: str) -> str | None:
        """Return the first non-empty line from text, if any."""
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line
        return None
