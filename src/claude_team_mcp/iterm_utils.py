"""
iTerm2 Utilities for Claude Team MCP

Low-level primitives for iTerm2 terminal control, extracted and adapted
from the original primitives.py for use in the MCP server.
"""

from typing import Optional, Callable
from pathlib import Path


# =============================================================================
# Key Codes
# =============================================================================

# Key codes for iTerm2 async_send_text()
# IMPORTANT: Use \x0d (Ctrl+M/carriage return) for Enter, NOT \n
KEYS = {
    "enter": "\x0d",  # Carriage return - the actual Enter key
    "return": "\x0d",
    "newline": "\n",  # Line feed - creates newline in text, doesn't submit
    "escape": "\x1b",
    "tab": "\t",
    "backspace": "\x7f",
    "delete": "\x1b[3~",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "ctrl-c": "\x03",  # Interrupt
    "ctrl-d": "\x04",  # EOF
    "ctrl-u": "\x15",  # Clear line
    "ctrl-l": "\x0c",  # Clear screen
    "ctrl-z": "\x1a",  # Suspend
}


# =============================================================================
# Terminal Control
# =============================================================================

async def send_text(session: "iterm2.Session", text: str) -> None:
    """
    Send raw text to an iTerm2 session.

    Note: This sends characters as-is. Use send_key() for special keys.
    """
    await session.async_send_text(text)


async def send_key(session: "iterm2.Session", key: str) -> None:
    """
    Send a special key to an iTerm2 session.

    Args:
        session: iTerm2 session object
        key: Key name (enter, escape, tab, backspace, up, down, left, right,
             ctrl-c, ctrl-u, ctrl-d, etc.)

    Raises:
        ValueError: If key name is not recognized
    """
    key_code = KEYS.get(key.lower())
    if key_code is None:
        raise ValueError(f"Unknown key: {key}. Available: {list(KEYS.keys())}")
    await session.async_send_text(key_code)


async def send_prompt(session: "iterm2.Session", text: str, submit: bool = True) -> None:
    """
    Send a prompt to an iTerm2 session, optionally submitting it.

    IMPORTANT: Uses \\x0d (Ctrl+M) for Enter, not \\n.
    iTerm2 interprets \\x0d as the actual Enter keypress.

    For multi-line text, iTerm2 uses bracketed paste mode which wraps the
    content in escape sequences. A delay is needed after pasting multi-line
    content before sending Enter to ensure the paste operation completes.

    Args:
        session: iTerm2 session object
        text: The text to send
        submit: If True, press Enter after sending text
    """
    import asyncio

    await session.async_send_text(text)
    if submit:
        # Always add a small delay before sending Enter to ensure the text paste
        # is fully processed by iTerm2. This is critical in async contexts (like
        # MCP servers) where the event loop may schedule Enter before the paste
        # completes. Multi-line text needs more time due to bracketed paste mode.
        delay = 0.1 if "\n" in text else 0.05
        await asyncio.sleep(delay)
        await session.async_send_text(KEYS["enter"])


async def read_screen(session: "iterm2.Session") -> list[str]:
    """
    Read all lines from an iTerm2 session's screen.

    Args:
        session: iTerm2 session object

    Returns:
        List of strings, one per line
    """
    screen = await session.async_get_screen_contents()
    return [screen.line(i).string for i in range(screen.number_of_lines)]


async def read_screen_text(session: "iterm2.Session") -> str:
    """
    Read screen content as a single string.

    Args:
        session: iTerm2 session object

    Returns:
        Screen content as newline-separated string
    """
    lines = await read_screen(session)
    return "\n".join(lines)


# =============================================================================
# Window Management
# =============================================================================

async def create_window(connection: "iterm2.Connection") -> "iterm2.Window":
    """
    Create a new iTerm2 window.

    Args:
        connection: iTerm2 connection object

    Returns:
        New window object
    """
    import iterm2
    return await iterm2.Window.async_create(connection)


async def create_tab(window: "iterm2.Window") -> "iterm2.Tab":
    """
    Create a new tab in an existing window.

    Args:
        window: iTerm2 window object

    Returns:
        New tab object
    """
    return await window.async_create_tab()


async def split_pane(
    session: "iterm2.Session",
    vertical: bool = True,
    before: bool = False,
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
    return await session.async_split_pane(vertical=vertical, before=before)


async def close_pane(session: "iterm2.Session", force: bool = False) -> bool:
    """
    Close an iTerm2 session/pane.

    Uses the iTerm2 async_close() API to terminate the pane. If the pane is the
    last one in a tab/window, the tab/window will also close.

    Args:
        session: The iTerm2 session to close
        force: If True, forcefully close even if processes are running

    Returns:
        True if the pane was closed successfully
    """
    await session.async_close(force=force)
    return True


# =============================================================================
# Shell Readiness Detection
# =============================================================================

# Common shell prompt endings that indicate the shell is ready for input.
# These appear at the end of the last non-empty line when shell is idle.
SHELL_PROMPT_PATTERNS = ['$ ', '% ', '> ', '# ', '❯ ', '➜ ']


async def wait_for_shell_ready(
    session: "iterm2.Session",
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.1,
    stable_count: int = 2,
) -> bool:
    """
    Wait for the shell to be ready to accept input.

    Polls the screen content and waits for a stable shell prompt to appear.
    A prompt is considered "stable" when the screen content hasn't changed
    for `stable_count` consecutive polls AND ends with a recognized prompt.

    Args:
        session: iTerm2 session to monitor
        timeout_seconds: Maximum time to wait for shell readiness
        poll_interval: Time between screen content checks
        stable_count: Number of consecutive stable reads before considering ready

    Returns:
        True if shell became ready, False if timeout was reached
    """
    import asyncio
    import time

    start_time = time.monotonic()
    last_content = None
    stable_reads = 0

    while (time.monotonic() - start_time) < timeout_seconds:
        try:
            content = await read_screen_text(session)

            # Find the last non-empty line (the prompt line)
            lines = content.rstrip().split('\n')
            last_line = ''
            for line in reversed(lines):
                stripped = line.rstrip()
                if stripped:
                    last_line = stripped
                    break

            # Check if content is stable (same as last read)
            if content == last_content:
                stable_reads += 1
            else:
                stable_reads = 0
                last_content = content

            # Check if we have a stable shell prompt
            if stable_reads >= stable_count:
                # Look for shell prompt at end of last line
                for pattern in SHELL_PROMPT_PATTERNS:
                    if last_line.endswith(pattern.rstrip()):
                        return True
                # Also check if line ends with common prompt chars
                if last_line and last_line[-1] in '$%>#':
                    return True

        except Exception:
            # Screen read failed, retry
            pass

        await asyncio.sleep(poll_interval)

    return False


# =============================================================================
# Claude Session Control
# =============================================================================

async def start_claude_in_session(
    session: "iterm2.Session",
    project_path: str,
    resume_session: Optional[str] = None,
    wait_seconds: float = 3.0,
    dangerously_skip_permissions: bool = False,
    env: Optional[dict[str, str]] = None,
    shell_ready_timeout: float = 10.0,
) -> None:
    """
    Start Claude Code in an existing iTerm2 session.

    Changes to the project directory and launches Claude Code. Waits for shell
    readiness before sending commands to prevent garbled input.

    Args:
        session: iTerm2 session to use
        project_path: Directory to run Claude in
        resume_session: Optional session ID to resume
        wait_seconds: Time to wait for Claude to initialize after starting
        dangerously_skip_permissions: If True, start with --dangerously-skip-permissions
        env: Optional dict of environment variables to set before running claude
        shell_ready_timeout: Max seconds to wait for shell prompt before each command
    """
    import asyncio

    # Wait for shell to be ready before sending cd command
    await wait_for_shell_ready(session, timeout_seconds=shell_ready_timeout)

    # Change to project directory
    await send_prompt(session, f"cd {project_path}")

    # Wait for shell to be ready after cd before sending claude command
    await wait_for_shell_ready(session, timeout_seconds=shell_ready_timeout)

    # Build and run claude command
    cmd = "claude"
    if dangerously_skip_permissions:
        cmd += " --dangerously-skip-permissions"
    if resume_session:
        cmd += f" --resume {resume_session}"

    # Prepend environment variables if provided
    if env:
        env_exports = " ".join(f"{k}={v}" for k, v in env.items())
        cmd = f"{env_exports} {cmd}"

    await send_prompt(session, cmd)

    # Wait for Claude to initialize
    await asyncio.sleep(wait_seconds)


# =============================================================================
# Multi-Pane Layouts
# =============================================================================

# Valid pane names for each layout type
LAYOUT_PANE_NAMES = {
    "vertical": ["left", "right"],
    "horizontal": ["top", "bottom"],
    "quad": ["top_left", "top_right", "bottom_left", "bottom_right"],
    "triple_vertical": ["left", "middle", "right"],
}


async def create_multi_pane_layout(
    connection: "iterm2.Connection",
    layout: str,
) -> dict[str, "iterm2.Session"]:
    """
    Create a new iTerm2 window with a multi-pane layout.

    Creates a window and splits it into panes according to the specified layout.
    Returns a mapping of pane names to iTerm2 sessions.

    Args:
        connection: iTerm2 connection object
        layout: Layout type - one of:
            - "vertical": 2 panes side by side (left, right)
            - "horizontal": 2 panes stacked (top, bottom)
            - "quad": 4 panes in 2x2 grid (top_left, top_right, bottom_left, bottom_right)
            - "triple_vertical": 3 panes side by side (left, middle, right)

    Returns:
        Dict mapping pane names to iTerm2 sessions

    Raises:
        ValueError: If layout is not recognized
    """
    if layout not in LAYOUT_PANE_NAMES:
        raise ValueError(
            f"Unknown layout: {layout}. Valid: {list(LAYOUT_PANE_NAMES.keys())}"
        )

    # Create window with initial session
    window = await create_window(connection)
    initial_session = window.current_tab.current_session

    panes: dict[str, "iterm2.Session"] = {}

    if layout == "vertical":
        # Split into left and right
        panes["left"] = initial_session
        panes["right"] = await split_pane(initial_session, vertical=True)

    elif layout == "horizontal":
        # Split into top and bottom
        panes["top"] = initial_session
        panes["bottom"] = await split_pane(initial_session, vertical=False)

    elif layout == "quad":
        # Create 2x2 grid:
        # 1. Split vertically: left | right
        # 2. Split left horizontally: top_left / bottom_left
        # 3. Split right horizontally: top_right / bottom_right
        left = initial_session
        right = await split_pane(left, vertical=True)

        # Split the left column
        panes["top_left"] = left
        panes["bottom_left"] = await split_pane(left, vertical=False)

        # Split the right column
        panes["top_right"] = right
        panes["bottom_right"] = await split_pane(right, vertical=False)

    elif layout == "triple_vertical":
        # Create 3 vertical panes: left | middle | right
        # 1. Split initial into 2
        # 2. Split right pane into 2 more
        panes["left"] = initial_session
        right_section = await split_pane(initial_session, vertical=True)
        panes["middle"] = right_section
        panes["right"] = await split_pane(right_section, vertical=True)

    return panes


async def create_multi_claude_layout(
    connection: "iterm2.Connection",
    projects: dict[str, str],
    layout: str,
    skip_permissions: bool = False,
    project_envs: Optional[dict[str, dict[str, str]]] = None,
) -> dict[str, "iterm2.Session"]:
    """
    Create a multi-pane window and start Claude Code in each pane.

    High-level primitive that combines create_multi_pane_layout with
    starting Claude in each pane.

    Args:
        connection: iTerm2 connection object
        projects: Dict mapping pane names to project paths. Keys must match
            the expected pane names for the layout (e.g., for 'quad':
            'top_left', 'top_right', 'bottom_left', 'bottom_right')
        layout: Layout type (vertical, horizontal, quad, triple_vertical)
        skip_permissions: If True, start Claude with --dangerously-skip-permissions
        project_envs: Optional dict mapping pane names to env var dicts. Each
            pane can have its own environment variables set before starting Claude.

    Returns:
        Dict mapping pane names to iTerm2 sessions (after Claude is started)

    Raises:
        ValueError: If layout is invalid or project keys don't match layout panes
    """
    import asyncio

    # Validate pane names match the layout
    expected_panes = set(LAYOUT_PANE_NAMES.get(layout, []))
    provided_panes = set(projects.keys())

    if not provided_panes.issubset(expected_panes):
        invalid = provided_panes - expected_panes
        raise ValueError(
            f"Invalid pane names for layout '{layout}': {invalid}. "
            f"Valid names: {expected_panes}"
        )

    # Create the pane layout
    panes = await create_multi_pane_layout(connection, layout)

    # Start Claude in all panes in parallel.
    # Each start_claude_in_session call uses wait_for_shell_ready() internally
    # which provides proper readiness detection, so no sleeps between starts needed.
    async def start_claude_for_pane(pane_name: str, project_path: str) -> None:
        session = panes[pane_name]
        pane_env = project_envs.get(pane_name) if project_envs else None
        await start_claude_in_session(
            session=session,
            project_path=project_path,
            dangerously_skip_permissions=skip_permissions,
            env=pane_env,
        )

    await asyncio.gather(*[
        start_claude_for_pane(pane_name, project_path)
        for pane_name, project_path in projects.items()
    ])

    # Return only the panes that were used
    return {name: panes[name] for name in projects.keys()}


# =============================================================================
# Window/Pane Introspection
# =============================================================================


MAX_PANES_PER_TAB = 4  # Maximum panes before considering tab "full"


def count_panes_in_tab(tab: "iterm2.Tab") -> int:
    """
    Count the number of panes (sessions) in a tab.

    Args:
        tab: iTerm2 tab object

    Returns:
        Number of sessions in the tab
    """
    return len(tab.sessions)


def count_panes_in_window(window: "iterm2.Window") -> int:
    """
    Count total panes across all tabs in a window.

    Note: For smart layout purposes, we typically care about individual tabs
    since panes are split within a tab. Use count_panes_in_tab() for that.

    Args:
        window: iTerm2 window object

    Returns:
        Total number of sessions across all tabs in the window
    """
    total = 0
    for tab in window.tabs:
        total += len(tab.sessions)
    return total


async def find_available_window(
    app: "iterm2.App",
    max_panes: int = MAX_PANES_PER_TAB,
) -> Optional[tuple["iterm2.Window", "iterm2.Tab", "iterm2.Session"]]:
    """
    Find a window with an available tab that has room for more panes.

    Searches all terminal windows for a tab with fewer than max_panes sessions.
    Returns the window, tab, and a session in that tab that can be split.

    Args:
        app: iTerm2 app object
        max_panes: Maximum panes before considering a tab full (default 4)

    Returns:
        Tuple of (window, tab, session) if found, None if all tabs are full
    """
    for window in app.terminal_windows:
        for tab in window.tabs:
            pane_count = count_panes_in_tab(tab)
            if pane_count < max_panes:
                # Return the current session in this tab as the split target
                current_session = tab.current_session
                if current_session:
                    return (window, tab, current_session)
    return None


async def get_window_for_session(
    app: "iterm2.App",
    session: "iterm2.Session",
) -> Optional["iterm2.Window"]:
    """
    Find the window containing a given session.

    Args:
        app: iTerm2 app object
        session: The session to find

    Returns:
        The window containing the session, or None if not found
    """
    for window in app.terminal_windows:
        for tab in window.tabs:
            for s in tab.sessions:
                if s.session_id == session.session_id:
                    return window
    return None


async def find_claude_session(
    app: "iterm2.App",
    project_path: str,
    match_fn: Optional[Callable[[str], bool]] = None,
) -> Optional["iterm2.Session"]:
    """
    Find an iTerm2 session that appears to be running Claude Code.

    Searches all windows/tabs for sessions whose screen contains
    indicators of Claude Code (e.g., project path, "Opus", prompt char).

    Args:
        app: iTerm2 app object
        project_path: Expected project path
        match_fn: Optional custom matcher function(screen_text) -> bool

    Returns:
        iTerm2 session if found, None otherwise
    """
    # Default matcher looks for Claude indicators
    if match_fn is None:
        project_name = Path(project_path).name

        def match_fn(text: str) -> bool:
            return (
                project_name in text
                and ("Opus" in text or "Sonnet" in text or "Haiku" in text)
                and ">" in text
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
