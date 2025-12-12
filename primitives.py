#!/usr/bin/env python3
"""
Claude Code iTerm2 Control Primitives

Core building blocks for programmatic control of Claude Code sessions
via iTerm2's Python API combined with session state from JSONL files.

Primitives:
    - Terminal Control: Send keystrokes, read screen
    - Session Discovery: Find Claude sessions from JSONL files
    - Session Linking: Map iTerm2 sessions to Claude JSONL sessions
    - Input Injection: Send prompts with proper Enter key handling
    - Response Detection: Wait for Claude to finish responding
    - Window Management: Create/split windows and panes
"""

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterator, Callable

try:
    import iterm2
except ImportError:
    iterm2 = None


# =============================================================================
# CONSTANTS
# =============================================================================

# Key codes for iTerm2 async_send_text()
# IMPORTANT: Use \x0d (Ctrl+M/carriage return) for Enter, NOT \n
KEYS = {
    'enter': '\x0d',      # Carriage return - the actual Enter key
    'return': '\x0d',
    'newline': '\n',      # Line feed - creates newline in text, doesn't submit
    'escape': '\x1b',
    'tab': '\t',
    'backspace': '\x7f',
    'delete': '\x1b[3~',
    'up': '\x1b[A',
    'down': '\x1b[B',
    'right': '\x1b[C',
    'left': '\x1b[D',
    'home': '\x1b[H',
    'end': '\x1b[F',
    'ctrl-c': '\x03',     # Interrupt
    'ctrl-d': '\x04',     # EOF
    'ctrl-u': '\x15',     # Clear line
    'ctrl-l': '\x0c',     # Clear screen
    'ctrl-z': '\x1a',     # Suspend
}

# Claude projects directory
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


# =============================================================================
# SESSION STATE (from JSONL files)
# =============================================================================

@dataclass
class Message:
    """A single message from a Claude session."""
    uuid: str
    parent_uuid: Optional[str]
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    tool_uses: list = field(default_factory=list)

    def __repr__(self):
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
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg
        return None

    @property
    def last_assistant_message(self) -> Optional[Message]:
        for msg in reversed(self.messages):
            if msg.role == "assistant" and msg.content:
                return msg
        return None

    @property
    def conversation(self) -> list[Message]:
        """User and assistant messages with content."""
        return [m for m in self.messages if m.role in ("user", "assistant") and m.content]


# =============================================================================
# PRIMITIVE: Session Discovery
# =============================================================================

def get_project_slug(project_path: str) -> str:
    """
    Convert a filesystem path to Claude's project directory slug.

    Claude replaces / with - to create directory names.
    Example: /Users/josh/code -> -Users-josh-code
    """
    return project_path.replace("/", "-")


def get_project_dir(project_path: str) -> Path:
    """Get the Claude projects directory for a given project path."""
    return CLAUDE_PROJECTS_DIR / get_project_slug(project_path)


def list_sessions(project_path: str) -> list[tuple[str, Path, float]]:
    """
    List all Claude sessions for a project.

    Returns: List of (session_id, jsonl_path, mtime) sorted by mtime desc
    """
    project_dir = get_project_dir(project_path)
    if not project_dir.exists():
        return []

    sessions = []
    for f in project_dir.glob("*.jsonl"):
        if f.name.startswith("agent-"):  # Skip subagent files
            continue
        sessions.append((f.stem, f, f.stat().st_mtime))

    return sorted(sessions, key=lambda x: x[2], reverse=True)


def find_active_session(project_path: str, max_age_seconds: int = 300) -> Optional[str]:
    """
    Find the most recently active session (modified within max_age_seconds).

    Useful for identifying which JSONL file corresponds to a running Claude instance.
    """
    sessions = list_sessions(project_path)
    if not sessions:
        return None

    session_id, _, mtime = sessions[0]
    if time.time() - mtime < max_age_seconds:
        return session_id
    return None


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
    """
    messages = []
    session_id = jsonl_path.stem
    project_path = ""

    with open(jsonl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "file-history-snapshot":
                continue

            if "cwd" in entry and not project_path:
                project_path = entry["cwd"]

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
                            tool_uses.append({
                                "name": item.get("name"),
                                "input": item.get("input", {})
                            })
                text_content = "\n".join(text_parts)

            # Parse timestamp
            try:
                ts = datetime.fromisoformat(entry.get("timestamp", "").replace("Z", "+00:00"))
            except:
                ts = datetime.now()

            messages.append(Message(
                uuid=entry.get("uuid", ""),
                parent_uuid=entry.get("parentUuid"),
                role=role,
                content=text_content,
                timestamp=ts,
                tool_uses=tool_uses
            ))

    return SessionState(
        session_id=session_id,
        project_path=project_path,
        jsonl_path=jsonl_path,
        messages=messages,
        last_modified=jsonl_path.stat().st_mtime if jsonl_path.exists() else 0
    )


def watch_session(jsonl_path: Path, poll_interval: float = 0.5) -> Iterator[SessionState]:
    """
    Generator that yields SessionState whenever the file changes.

    Blocking iterator - use in a separate thread or with asyncio.to_thread().
    """
    last_mtime = 0
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
# PRIMITIVE: Terminal Control (requires iterm2)
# =============================================================================

def require_iterm2():
    """Raise if iterm2 module not available."""
    if iterm2 is None:
        raise ImportError(
            "iterm2 package required. Install with: pip install iterm2\n"
            "Also enable: iTerm2 → Preferences → General → Magic → Enable Python API"
        )


async def send_text(session: "iterm2.Session", text: str):
    """
    Send raw text to an iTerm2 session.

    Note: This sends characters as-is. Use send_key() for special keys.
    """
    require_iterm2()
    await session.async_send_text(text)


async def send_key(session: "iterm2.Session", key: str):
    """
    Send a special key to an iTerm2 session.

    Keys: enter, escape, tab, backspace, up, down, left, right,
          ctrl-c, ctrl-u, ctrl-d, etc.
    """
    require_iterm2()
    key_code = KEYS.get(key.lower())
    if key_code is None:
        raise ValueError(f"Unknown key: {key}. Available: {list(KEYS.keys())}")
    await session.async_send_text(key_code)


async def send_prompt(session: "iterm2.Session", text: str, submit: bool = True):
    """
    Send a prompt to an iTerm2 session, optionally submitting it.

    IMPORTANT: Uses \\x0d (Ctrl+M) for Enter, not \\n.
    iTerm2 interprets \\x0d as the actual Enter keypress.
    """
    require_iterm2()
    await session.async_send_text(text)
    if submit:
        await session.async_send_text(KEYS['enter'])


async def read_screen(session: "iterm2.Session") -> list[str]:
    """
    Read all lines from an iTerm2 session's screen.

    Returns list of strings, one per line.
    """
    require_iterm2()
    screen = await session.async_get_screen_contents()
    return [screen.line(i).string for i in range(screen.number_of_lines)]


async def read_screen_text(session: "iterm2.Session") -> str:
    """Read screen as single string."""
    lines = await read_screen(session)
    return "\n".join(lines)


# =============================================================================
# PRIMITIVE: Session Linking (iTerm2 <-> JSONL)
# =============================================================================

@dataclass
class LinkedSession:
    """
    A Claude Code session linked to both iTerm2 and JSONL state.

    This is the core primitive for controlling Claude Code - it maintains
    the connection between the visual terminal and the structured state.
    """
    iterm_session: "iterm2.Session"
    project_path: str
    session_id: Optional[str] = None
    _state: Optional[SessionState] = None

    def refresh_state(self) -> Optional[SessionState]:
        """Reload state from JSONL file."""
        if not self.session_id:
            self.session_id = find_active_session(self.project_path)

        if self.session_id:
            jsonl_path = get_project_dir(self.project_path) / f"{self.session_id}.jsonl"
            if jsonl_path.exists():
                self._state = parse_session(jsonl_path)

        return self._state

    @property
    def state(self) -> Optional[SessionState]:
        """Get cached state (call refresh_state() to update)."""
        return self._state

    async def send(self, text: str, submit: bool = True):
        """Send text to the terminal, optionally pressing Enter."""
        await send_prompt(self.iterm_session, text, submit)

    async def send_key(self, key: str):
        """Send a special key (enter, escape, ctrl-c, etc.)."""
        await send_key(self.iterm_session, key)

    async def read_screen(self) -> str:
        """Read current terminal screen."""
        return await read_screen_text(self.iterm_session)

    async def wait_for_response(
        self,
        timeout: float = 120,
        poll_interval: float = 0.5,
        idle_threshold: float = 2.0
    ) -> Optional[Message]:
        """
        Wait for Claude to finish responding.

        Monitors the JSONL file modification time. When it stops changing
        for idle_threshold seconds, assumes Claude is done.
        """
        start = time.time()
        last_change = start
        last_mtime = 0

        await asyncio.sleep(1)  # Initial delay for Claude to start

        while time.time() - start < timeout:
            self.refresh_state()

            if self._state:
                current_mtime = self._state.last_modified
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    last_change = time.time()
                elif time.time() - last_change > idle_threshold:
                    return self._state.last_assistant_message

            await asyncio.sleep(poll_interval)

        return None


async def link_session(
    iterm_session: "iterm2.Session",
    project_path: str,
    session_id: Optional[str] = None
) -> LinkedSession:
    """
    Create a LinkedSession from an existing iTerm2 session.

    If session_id is not provided, attempts to discover it from
    recently modified JSONL files.
    """
    linked = LinkedSession(
        iterm_session=iterm_session,
        project_path=project_path,
        session_id=session_id
    )
    linked.refresh_state()
    return linked


async def find_claude_session(
    app: "iterm2.App",
    project_path: str,
    match_fn: Optional[Callable[[str], bool]] = None
) -> Optional["iterm2.Session"]:
    """
    Find an iTerm2 session that appears to be running Claude Code.

    Searches all windows/tabs for sessions whose screen contains
    indicators of Claude Code (e.g., project path, "Opus", prompt char).

    Args:
        app: iTerm2 app object
        project_path: Expected project path
        match_fn: Optional custom matcher function(screen_text) -> bool
    """
    require_iterm2()

    # Default matcher looks for Claude indicators
    if match_fn is None:
        project_name = Path(project_path).name
        def match_fn(text: str) -> bool:
            return (
                project_name in text and
                ("Opus" in text or "Sonnet" in text or "Haiku" in text) and
                ">" in text
            )

    for window in app.terminal_windows:
        for tab in window.tabs:
            for session in tab.sessions:
                try:
                    text = await read_screen_text(session)
                    if match_fn(text):
                        return session
                except Exception:
                    continue

    return None


# =============================================================================
# PRIMITIVE: Window Management
# =============================================================================

async def create_window(connection: "iterm2.Connection") -> "iterm2.Window":
    """Create a new iTerm2 window."""
    require_iterm2()
    return await iterm2.Window.async_create(connection)


async def create_tab(window: "iterm2.Window") -> "iterm2.Tab":
    """Create a new tab in an existing window."""
    require_iterm2()
    return await window.async_create_tab()


async def split_pane(
    session: "iterm2.Session",
    vertical: bool = True,
    before: bool = False
) -> "iterm2.Session":
    """
    Split an iTerm2 session into two panes.

    Args:
        session: The session to split
        vertical: If True, split vertically (side by side). If False, horizontal (stacked).
        before: If True, new pane appears before/above. If False, after/below.

    Returns:
        The new session created in the split pane.
    """
    require_iterm2()
    return await session.async_split_pane(vertical=vertical, before=before)


async def get_all_sessions(app: "iterm2.App") -> list[tuple["iterm2.Window", "iterm2.Tab", "iterm2.Session"]]:
    """
    Get all sessions across all windows and tabs.

    Returns: List of (window, tab, session) tuples.
    """
    require_iterm2()
    results = []
    for window in app.terminal_windows:
        for tab in window.tabs:
            for session in tab.sessions:
                results.append((window, tab, session))
    return results


# =============================================================================
# PRIMITIVE: Claude Session Lifecycle
# =============================================================================

async def start_claude(
    session: "iterm2.Session",
    project_path: str,
    resume_session: Optional[str] = None,
    wait_seconds: float = 3.0
) -> LinkedSession:
    """
    Start Claude Code in an iTerm2 session.

    Args:
        session: iTerm2 session to use
        project_path: Directory to run Claude in
        resume_session: Optional session ID to resume
        wait_seconds: Time to wait for Claude to initialize

    Returns:
        LinkedSession ready for interaction
    """
    require_iterm2()

    # Change to project directory
    await send_prompt(session, f"cd {project_path}")
    await asyncio.sleep(0.3)

    # Build and run claude command
    cmd = "claude"
    if resume_session:
        cmd += f" --resume {resume_session}"
    await send_prompt(session, cmd)

    # Wait for Claude to initialize
    await asyncio.sleep(wait_seconds)

    # Create linked session
    linked = LinkedSession(
        iterm_session=session,
        project_path=project_path,
        session_id=resume_session
    )
    linked.refresh_state()

    return linked


async def create_claude_session(
    connection: "iterm2.Connection",
    project_path: str,
    in_new_window: bool = True,
    resume_session: Optional[str] = None
) -> LinkedSession:
    """
    Create a new Claude Code session in a new window or tab.

    This is a convenience function that:
    1. Creates a new window or tab
    2. Starts Claude Code in it
    3. Returns a LinkedSession for interaction
    """
    require_iterm2()

    app = await iterm2.async_get_app(connection)

    if in_new_window:
        window = await create_window(connection)
        session = window.current_tab.current_session
    else:
        window = app.current_terminal_window
        if window is None:
            window = await create_window(connection)
            session = window.current_tab.current_session
        else:
            tab = await create_tab(window)
            session = tab.current_session

    return await start_claude(session, project_path, resume_session)


# =============================================================================
# PRIMITIVE: Multi-Pane Layouts
# =============================================================================

@dataclass
class PaneLayout:
    """
    A multi-pane window layout with Claude sessions.

    Provides named access to panes and their Claude sessions.
    """
    window: "iterm2.Window"
    panes: dict[str, "iterm2.Session"]
    sessions: dict[str, LinkedSession] = field(default_factory=dict)

    async def start_claude_in_pane(
        self,
        pane_name: str,
        project_path: str,
        wait_seconds: float = 3.0
    ) -> LinkedSession:
        """Start Claude in a specific pane and return LinkedSession."""
        if pane_name not in self.panes:
            raise ValueError(f"Unknown pane: {pane_name}. Available: {list(self.panes.keys())}")

        linked = await start_claude(self.panes[pane_name], project_path, wait_seconds=wait_seconds)
        self.sessions[pane_name] = linked
        return linked

    async def send_to_pane(self, pane_name: str, text: str, submit: bool = True):
        """Send text to a specific pane."""
        if pane_name not in self.panes:
            raise ValueError(f"Unknown pane: {pane_name}")
        await send_prompt(self.panes[pane_name], text, submit)

    async def read_pane(self, pane_name: str) -> str:
        """Read screen content from a specific pane."""
        if pane_name not in self.panes:
            raise ValueError(f"Unknown pane: {pane_name}")
        return await read_screen_text(self.panes[pane_name])


async def create_split_layout(
    connection: "iterm2.Connection",
    layout: str = "vertical"
) -> PaneLayout:
    """
    Create a window with split panes.

    Args:
        connection: iTerm2 connection
        layout: One of:
            - "vertical": Two panes side by side [left, right]
            - "horizontal": Two panes stacked [top, bottom]
            - "quad": Four panes in 2x2 grid [top_left, top_right, bottom_left, bottom_right]
            - "triple_vertical": Three panes side by side [left, center, right]

    Returns:
        PaneLayout with named panes
    """
    require_iterm2()

    window = await create_window(connection)
    main = window.current_tab.current_session

    if layout == "vertical":
        right = await main.async_split_pane(vertical=True, before=False)
        panes = {"left": main, "right": right}

    elif layout == "horizontal":
        bottom = await main.async_split_pane(vertical=False, before=False)
        panes = {"top": main, "bottom": bottom}

    elif layout == "quad":
        # Split main vertically first
        right = await main.async_split_pane(vertical=True, before=False)
        # Split each half horizontally
        bottom_left = await main.async_split_pane(vertical=False, before=False)
        bottom_right = await right.async_split_pane(vertical=False, before=False)
        panes = {
            "top_left": main,
            "top_right": right,
            "bottom_left": bottom_left,
            "bottom_right": bottom_right
        }

    elif layout == "triple_vertical":
        center = await main.async_split_pane(vertical=True, before=False)
        right = await center.async_split_pane(vertical=True, before=False)
        panes = {"left": main, "center": center, "right": right}

    else:
        raise ValueError(f"Unknown layout: {layout}. Use: vertical, horizontal, quad, triple_vertical")

    return PaneLayout(window=window, panes=panes)


async def create_multi_claude_layout(
    connection: "iterm2.Connection",
    projects: dict[str, str],
    layout: str = "vertical"
) -> PaneLayout:
    """
    Create a multi-pane layout with Claude running in each pane.

    Args:
        connection: iTerm2 connection
        projects: Dict mapping pane names to project paths
            e.g., {"left": "/path/to/frontend", "right": "/path/to/backend"}
        layout: Layout type (see create_split_layout)

    Returns:
        PaneLayout with Claude sessions started in each pane

    Example:
        layout = await create_multi_claude_layout(connection, {
            "left": "/Users/josh/frontend",
            "right": "/Users/josh/backend"
        })
        await layout.sessions["left"].send("What's the React version?")
        await layout.sessions["right"].send("What's the Python version?")
    """
    pane_layout = await create_split_layout(connection, layout)

    for pane_name, project_path in projects.items():
        if pane_name in pane_layout.panes:
            await pane_layout.start_claude_in_pane(pane_name, project_path)

    return pane_layout
