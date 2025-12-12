#!/usr/bin/env python3
"""
Claude Code Controller via iTerm2 API + JSONL Session Parsing

Allows programmatic control of Claude Code sessions while maintaining
visual access for human intervention.

Usage:
    # As a library
    from claude_controller import ClaudeSessionManager

    async with ClaudeSessionManager() as manager:
        session = await manager.create_session("/path/to/project")
        await session.send_prompt("List the files")
        await session.wait_for_response()
        state = session.get_state()
        print(state.last_assistant_message)

    # Or run the demo
    python claude_controller.py

Requirements:
    pip install iterm2

    Also enable: iTerm2 → Preferences → General → Magic → Enable Python API
"""

import asyncio
import os
import time
from typing import Optional

# Import iterm2 - required for this module
try:
    import iterm2
except ImportError:
    raise ImportError(
        "iterm2 package required. Install with: pip install iterm2\n"
        "Also enable: iTerm2 → Preferences → General → Magic → Enable Python API"
    )

# Import session parser (no external deps beyond stdlib)
from session_parser import SessionParser, SessionState, Message


class ClaudeSession:
    """
    Controls a single Claude Code session via iTerm2 + JSONL monitoring.

    Combines iTerm2's ability to send keystrokes with parsing the session
    JSONL file for structured access to conversation state.
    """

    def __init__(
        self,
        iterm_session: "iterm2.Session",
        project_path: str,
        session_id: Optional[str] = None
    ):
        """
        Initialize a Claude session controller.

        Args:
            iterm_session: The iTerm2 session running Claude Code
            project_path: Directory where Claude is running
            session_id: Optional known session ID (discovered automatically if not provided)
        """
        self.iterm_session = iterm_session
        self.project_path = project_path
        self._session_id = session_id
        self._state: Optional[SessionState] = None

    @property
    def session_id(self) -> Optional[str]:
        """Get the Claude session ID (discovered from JSONL)."""
        if self._session_id:
            return self._session_id
        if self._state:
            return self._state.session_id
        return None

    async def send_prompt(self, prompt: str, submit: bool = True):
        """
        Send a prompt to the Claude Code session.

        Args:
            prompt: The text to send
            submit: If True, send carriage return to submit the prompt
        """
        await self.iterm_session.async_send_text(prompt)
        if submit:
            # Use Ctrl+M (carriage return \x0d) instead of \n
            # iTerm2 interprets \x0d as the actual Enter key
            await self.iterm_session.async_send_text("\x0d")

    async def send_escape(self):
        """Send Escape key (useful for canceling or exiting menus)."""
        await self.iterm_session.async_send_text("\x1b")

    async def send_interrupt(self):
        """Send Ctrl+C to interrupt current operation."""
        await self.iterm_session.async_send_text("\x03")

    async def send_key(self, key: str):
        """
        Send a special key sequence.

        Common keys: 'up', 'down', 'left', 'right', 'enter', 'tab'
        """
        key_map = {
            'up': '\x1b[A',
            'down': '\x1b[B',
            'right': '\x1b[C',
            'left': '\x1b[D',
            'enter': '\x0d',  # Carriage return (Ctrl+M)
            'return': '\x0d',
            'tab': '\t',
            'escape': '\x1b',
            'backspace': '\x7f',
            'ctrl-c': '\x03',
            'ctrl-u': '\x15',  # Clear line
        }
        if key.lower() in key_map:
            await self.iterm_session.async_send_text(key_map[key.lower()])
        else:
            await self.iterm_session.async_send_text(key)

    async def get_screen(self) -> str:
        """Get current terminal screen contents (visible area)."""
        screen = await self.iterm_session.async_get_screen_contents()
        lines = []
        for i in range(screen.number_of_lines):
            line = screen.line(i)
            lines.append(line.string)
        return "\n".join(lines)

    def get_state(self) -> Optional[SessionState]:
        """Get the current session state from JSONL (cached)."""
        return self._state

    def refresh_state(self) -> Optional[SessionState]:
        """Force refresh the session state from JSONL file."""
        if not self._session_id:
            # Try to discover session ID from recently modified files
            self._session_id = SessionParser.find_active_session(self.project_path)

        if self._session_id:
            project_dir = SessionParser.get_project_dir(self.project_path)
            jsonl_path = project_dir / f"{self._session_id}.jsonl"
            if jsonl_path.exists():
                self._state = SessionParser.parse_session(jsonl_path)

        return self._state

    async def wait_for_response(
        self,
        timeout: float = 120,
        poll_interval: float = 0.5,
        idle_threshold: float = 2.0
    ) -> Optional[Message]:
        """
        Wait for Claude to finish responding.

        Uses JSONL file modification time to detect when Claude stops writing.
        This is more reliable than screen-scraping for detecting completion.

        Args:
            timeout: Maximum seconds to wait
            poll_interval: How often to check for changes
            idle_threshold: Seconds of no changes before considering complete

        Returns:
            The last assistant message, or None if timeout
        """
        start = time.time()
        last_change = start
        last_mtime = 0

        # Give Claude time to start writing
        await asyncio.sleep(1)

        while time.time() - start < timeout:
            self.refresh_state()

            if self._state:
                current_mtime = self._state.last_modified
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    last_change = time.time()
                elif time.time() - last_change > idle_threshold:
                    # No changes for idle_threshold seconds - Claude is done
                    return self._state.last_assistant_message

            await asyncio.sleep(poll_interval)

        return None  # Timeout

    async def wait_for_idle_screen(
        self,
        timeout: float = 60,
        poll_interval: float = 0.5,
        stable_count: int = 4
    ) -> bool:
        """
        Wait for the terminal screen to stop changing.

        This is a fallback method when JSONL watching isn't reliable.

        Args:
            timeout: Maximum seconds to wait
            poll_interval: How often to check
            stable_count: Number of consecutive unchanged polls needed

        Returns:
            True if idle detected, False if timeout
        """
        last_content = ""
        consecutive_same = 0
        start = time.time()

        while time.time() - start < timeout:
            current = await self.get_screen()
            if current == last_content:
                consecutive_same += 1
                if consecutive_same >= stable_count:
                    return True
            else:
                consecutive_same = 0
                last_content = current

            await asyncio.sleep(poll_interval)

        return False


class ClaudeSessionManager:
    """
    Manages multiple Claude Code sessions via iTerm2.

    Usage:
        async with ClaudeSessionManager() as manager:
            session = await manager.create_session("/path/to/project")
            await session.send_prompt("Hello!")
            response = await session.wait_for_response()
            print(response.content)
    """

    def __init__(self):
        self.connection: Optional["iterm2.Connection"] = None
        self.app: Optional["iterm2.App"] = None
        self.sessions: dict[str, ClaudeSession] = {}

    async def __aenter__(self):
        """Connect to iTerm2."""
        self.connection = await iterm2.Connection.async_create()
        self.app = await iterm2.async_get_app(self.connection)
        return self

    async def __aexit__(self, *args):
        """Cleanup (handled by iterm2 library)."""
        pass

    async def create_session(
        self,
        project_path: str,
        in_new_window: bool = True,
        resume_session: Optional[str] = None
    ) -> ClaudeSession:
        """
        Create a new Claude Code session in iTerm2.

        Args:
            project_path: Directory to run Claude in
            in_new_window: Create in new window (True) or new tab (False)
            resume_session: Optional session ID to resume

        Returns:
            ClaudeSession controller object
        """
        # Create window or tab
        if in_new_window:
            window = await iterm2.Window.async_create(self.connection)
            tab = window.current_tab
        else:
            window = self.app.current_terminal_window
            if window is None:
                window = await iterm2.Window.async_create(self.connection)
                tab = window.current_tab
            else:
                tab = await window.async_create_tab()

        iterm_session = tab.current_session

        # Change to project directory
        await iterm_session.async_send_text(f"cd {project_path}\n")
        await asyncio.sleep(0.3)

        # Build and run claude command
        cmd = "claude"
        if resume_session:
            cmd += f" --resume {resume_session}"
        await iterm_session.async_send_text(cmd + "\n")

        # Wait for Claude to initialize
        await asyncio.sleep(2)

        session = ClaudeSession(
            iterm_session=iterm_session,
            project_path=project_path,
            session_id=resume_session
        )

        # Try to discover the session ID
        session.refresh_state()

        if session.session_id:
            self.sessions[session.session_id] = session

        return session

    async def attach_to_session(
        self,
        iterm_session: "iterm2.Session",
        project_path: str,
        session_id: Optional[str] = None
    ) -> ClaudeSession:
        """
        Attach to an existing Claude session running in an iTerm2 session.

        Args:
            iterm_session: The iTerm2 session object
            project_path: Project directory path
            session_id: Optional known session ID

        Returns:
            ClaudeSession controller
        """
        if not session_id:
            session_id = SessionParser.find_active_session(project_path)

        session = ClaudeSession(
            iterm_session=iterm_session,
            project_path=project_path,
            session_id=session_id
        )

        session.refresh_state()

        if session.session_id:
            self.sessions[session.session_id] = session

        return session

    async def find_claude_sessions(self) -> list[tuple["iterm2.Session", str]]:
        """
        Find all iTerm2 sessions that appear to be running Claude.

        Returns:
            List of (iterm_session, detected_project_path) tuples
        """
        results = []

        for window in self.app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    try:
                        screen = await session.async_get_screen_contents()
                        # Check first few lines for Claude indicators
                        content = "\n".join(
                            screen.line(i).string
                            for i in range(min(10, screen.number_of_lines))
                        )

                        # Look for Claude's prompt or other indicators
                        if ">" in content or "claude" in content.lower():
                            # Try to extract project path from screen
                            # This is a heuristic - may need adjustment
                            results.append((session, os.getcwd()))

                    except Exception:
                        continue

        return results

    def list_project_sessions(self, project_path: str) -> list[tuple[str, str, float]]:
        """
        List all known Claude sessions for a project.

        Returns:
            List of (session_id, jsonl_path, mtime) tuples
        """
        return SessionParser.list_sessions(project_path)


# --- Demo ---

async def demo(connection):
    """Demonstration of the controller capabilities."""
    print("Claude Code iTerm2 Controller Demo")
    print("=" * 50)

    project_path = os.getcwd()
    print(f"\nProject path: {project_path}")

    # List existing sessions
    print("\nListing existing sessions...")
    sessions = SessionParser.list_sessions(project_path)
    if sessions:
        print(f"Found {len(sessions)} session(s):")
        for sid, path, mtime in sessions[:5]:
            age = time.time() - mtime
            print(f"  - {sid[:16]}... (modified {age:.0f}s ago)")
    else:
        print("No existing sessions found.")

    # Check for active session
    active = SessionParser.find_active_session(project_path)
    if active:
        print(f"\nActive session: {active[:16]}...")
        print("Parsing state...")

        project_dir = SessionParser.get_project_dir(project_path)
        state = SessionParser.parse_session(project_dir / f"{active}.jsonl")

        print(f"  Messages: {len(state.messages)}")
        if state.last_user_message:
            print(f"  Last user: {state.last_user_message.content[:80]}...")
        if state.last_assistant_message:
            print(f"  Last assistant: {state.last_assistant_message.content[:80]}...")

    print("\n" + "=" * 50)
    print("Usage example:")
    print("""
    async with ClaudeSessionManager() as manager:
        session = await manager.create_session("/path/to/project")
        await session.send_prompt("What files are here?")
        response = await session.wait_for_response()
        print(response.content)
    """)


if __name__ == "__main__":
    iterm2.run_until_complete(demo)
