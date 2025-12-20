"""
iTerm2 Utilities for Claude Team MCP

Low-level primitives for iTerm2 terminal control, extracted and adapted
from the original primitives.py for use in the MCP server.
"""

import logging
import re
import subprocess
from typing import Optional, Callable
from pathlib import Path

logger = logging.getLogger("claude-team-mcp.iterm_utils")


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
    The delay scales with text length since longer pastes take more time
    for the terminal to process.

    Args:
        session: iTerm2 session object
        text: The text to send
        submit: If True, press Enter after sending text
    """
    import asyncio

    await session.async_send_text(text)
    if submit:
        # Calculate delay based on text characteristics. Longer text and more
        # lines require more time for iTerm2's bracketed paste mode to process.
        # Without adequate delay, the Enter key arrives before paste completes,
        # resulting in the prompt not being submitted.
        line_count = text.count("\n")
        char_count = len(text)

        if line_count > 0:
            # Multi-line text: base delay + scaling factors for lines and chars.
            # - Base: 0.1s minimum for bracketed paste mode overhead
            # - Per line: 0.01s to account for line processing
            # - Per 1000 chars: 0.05s for large text buffers
            # Capped at 2.0s to avoid excessive waits on huge pastes.
            delay = min(2.0, 0.1 + (line_count * 0.01) + (char_count / 1000 * 0.05))
        else:
            # Single-line text: minimal delay, just enough for event loop sync
            delay = 0.05

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


def _calculate_screen_frame() -> tuple[float, float, float, float]:
    """
    Calculate a screen-filling window frame that avoids macOS fullscreen.

    Returns dimensions slightly smaller than full screen to ensure the window
    stays in the current Space rather than entering macOS fullscreen mode.

    Returns:
        Tuple of (x, y, width, height) in points for the window frame.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Parse resolution from output like "Resolution: 3840 x 2160"
        match = re.search(r"Resolution: (\d+) x (\d+)", result.stdout)
        if not match:
            logger.warning("Could not parse screen resolution, using defaults")
            return (0.0, 25.0, 1400.0, 900.0)

        screen_w, screen_h = int(match.group(1)), int(match.group(2))

        # Detect Retina display (2x scale factor)
        scale = 2 if "Retina" in result.stdout else 1
        logical_w = screen_w // scale
        logical_h = screen_h // scale

        # Leave space for menu bar (25px) and dock (~70px), plus small margins
        # to ensure we don't trigger fullscreen mode
        x = 0.0
        y = 25.0  # Below menu bar
        width = float(logical_w) - 10  # Small margin on right
        height = float(logical_h) - 100  # Space for menu bar and dock

        logger.debug(
            f"Screen {screen_w}x{screen_h} (scale {scale}) -> "
            f"window frame ({x}, {y}, {width}, {height})"
        )
        return (x, y, width, height)

    except subprocess.TimeoutExpired:
        logger.warning("system_profiler timed out, using default frame")
        return (0.0, 25.0, 1400.0, 900.0)
    except Exception as e:
        logger.warning(f"Failed to calculate screen frame: {e}")
        return (0.0, 25.0, 1400.0, 900.0)


async def create_window(
    connection: "iterm2.Connection",
    profile: Optional[str] = None,
    profile_customizations: Optional["iterm2.LocalWriteOnlyProfile"] = None,
) -> "iterm2.Window":
    """
    Create a new iTerm2 window with screen-filling dimensions.

    Creates the window, exits fullscreen if needed, and sets its frame to
    fill the screen without entering macOS fullscreen mode (staying in the
    current Space).

    Args:
        connection: iTerm2 connection object
        profile: Optional profile name to use for the window's initial session
        profile_customizations: Optional LocalWriteOnlyProfile with per-session
            customizations (tab color, badge, etc.) to apply to the initial session

    Returns:
        New window object
    """
    import iterm2

    # Create the window
    window = await iterm2.Window.async_create(
        connection,
        profile=profile,
        profile_customizations=profile_customizations,
    )

    # Exit fullscreen mode if the window opened in fullscreen
    # (can happen if user's default profile or iTerm2 settings use fullscreen)
    is_fullscreen = await window.async_get_fullscreen()
    if is_fullscreen:
        logger.info("Window opened in fullscreen, exiting fullscreen mode")
        await window.async_set_fullscreen(False)
        # Give macOS time to animate out of fullscreen
        import asyncio
        await asyncio.sleep(0.5)

    # Set window frame to fill screen without triggering fullscreen mode
    x, y, width, height = _calculate_screen_frame()
    frame = iterm2.Frame(
        origin=iterm2.Point(x, y),
        size=iterm2.Size(width, height),
    )
    await window.async_set_frame(frame)

    return window


async def split_pane(
    session: "iterm2.Session",
    vertical: bool = True,
    before: bool = False,
    profile: Optional[str] = None,
    profile_customizations: Optional["iterm2.LocalWriteOnlyProfile"] = None,
) -> "iterm2.Session":
    """
    Split an iTerm2 session into two panes.

    Args:
        session: The session to split
        vertical: If True, split vertically (side by side). If False, horizontal (stacked).
        before: If True, new pane appears before/above. If False, after/below.
        profile: Optional profile name to use for the new pane
        profile_customizations: Optional LocalWriteOnlyProfile with per-session
            customizations (tab color, badge, etc.) to apply to the new pane

    Returns:
        The new session created in the split pane.
    """
    return await session.async_split_pane(
        vertical=vertical,
        before=before,
        profile=profile,
        profile_customizations=profile_customizations,
    )


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
# Claude Readiness Detection
# =============================================================================

# Patterns that indicate Claude Code has started and is ready for input.
# These appear in Claude's startup banner (the ASCII robot art).
CLAUDE_READY_PATTERNS = [
    "Claude Code v",   # Version line in banner
    "▐▛███▜▌",         # Top of robot head
    "▝▜█████▛▘",       # Middle of robot
]


async def wait_for_claude_ready(
    session: "iterm2.Session",
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """
    Wait for Claude Code to start and display its banner.

    Polls the screen content looking for Claude's startup banner (the ASCII
    robot art and version text). This ensures Claude is actually running
    before we try to send it messages.

    Args:
        session: iTerm2 session to monitor
        timeout_seconds: Maximum time to wait for Claude to start
        poll_interval: Time between screen content checks

    Returns:
        True if Claude started successfully, False if timeout was reached
    """
    import asyncio
    import time

    start_time = time.monotonic()

    while (time.monotonic() - start_time) < timeout_seconds:
        try:
            content = await read_screen_text(session)

            # Check for any of the Claude banner patterns
            for pattern in CLAUDE_READY_PATTERNS:
                if pattern in content:
                    return True

        except Exception:
            # Screen read failed, retry
            pass

        await asyncio.sleep(poll_interval)

    return False


# =============================================================================
# Claude Session Control
# =============================================================================

def build_stop_hook_settings(marker_id: str) -> str:
    """
    Build the --settings JSON for Stop hook injection.

    The hook embeds a marker in the command text itself, which gets logged
    to the JSONL in the stop_hook_summary's hookInfos array. This provides
    reliable completion detection without needing stderr or exit code hacks.

    Args:
        marker_id: Unique ID to embed in the marker (typically session_id)

    Returns:
        JSON string suitable for --settings flag
    """
    import json

    settings = {
        "hooks": {
            "Stop": [{
                "hooks": [{
                    "type": "command",
                    "command": f"echo [worker-done:{marker_id}]"
                }]
            }]
        }
    }
    return json.dumps(settings, separators=(',', ':'))


async def start_claude_in_session(
    session: "iterm2.Session",
    project_path: str,
    dangerously_skip_permissions: bool = False,
    env: Optional[dict[str, str]] = None,
    shell_ready_timeout: float = 10.0,
    claude_ready_timeout: float = 30.0,
    stop_hook_marker_id: Optional[str] = None,
) -> None:
    """
    Start Claude Code in an existing iTerm2 session.

    Changes to the project directory and launches Claude Code. Waits for shell
    readiness before sending commands, then waits for Claude's startup banner
    to appear before returning.

    Args:
        session: iTerm2 session to use
        project_path: Directory to run Claude in
        dangerously_skip_permissions: If True, start with --dangerously-skip-permissions
        env: Optional dict of environment variables to set before running claude
        shell_ready_timeout: Max seconds to wait for shell prompt before each command
        claude_ready_timeout: Max seconds to wait for Claude to start and show banner
        stop_hook_marker_id: If provided, inject a Stop hook that logs this marker
            to the JSONL for completion detection

    Raises:
        RuntimeError: If Claude fails to start within the timeout
    """
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
    if stop_hook_marker_id:
        settings_json = build_stop_hook_settings(stop_hook_marker_id)
        cmd += f" --settings '{settings_json}'"

    # Prepend environment variables if provided
    if env:
        env_exports = " ".join(f"{k}={v}" for k, v in env.items())
        cmd = f"{env_exports} {cmd}"

    await send_prompt(session, cmd)

    # Wait for Claude to actually start (detect banner, not blind sleep)
    if not await wait_for_claude_ready(session, timeout_seconds=claude_ready_timeout):
        raise RuntimeError(
            f"Claude failed to start in {project_path} within {claude_ready_timeout}s. "
            "Check that 'claude' command is available and authentication is configured."
        )


# =============================================================================
# Multi-Pane Layouts
# =============================================================================

# Valid pane names for each layout type
LAYOUT_PANE_NAMES = {
    "single": ["main"],
    "vertical": ["left", "right"],
    "horizontal": ["top", "bottom"],
    "quad": ["top_left", "top_right", "bottom_left", "bottom_right"],
    "triple_vertical": ["left", "middle", "right"],
}


async def create_multi_pane_layout(
    connection: "iterm2.Connection",
    layout: str,
    profile: Optional[str] = None,
    profile_customizations: Optional[dict[str, "iterm2.LocalWriteOnlyProfile"]] = None,
) -> dict[str, "iterm2.Session"]:
    """
    Create a new iTerm2 window with a multi-pane layout.

    Creates a window and splits it into panes according to the specified layout.
    Returns a mapping of pane names to iTerm2 sessions.

    Args:
        connection: iTerm2 connection object
        layout: Layout type - one of:
            - "single": 1 pane, full window (main)
            - "vertical": 2 panes side by side (left, right)
            - "horizontal": 2 panes stacked (top, bottom)
            - "quad": 4 panes in 2x2 grid (top_left, top_right, bottom_left, bottom_right)
            - "triple_vertical": 3 panes side by side (left, middle, right)
        profile: Optional profile name to use for all panes
        profile_customizations: Optional dict mapping pane names to LocalWriteOnlyProfile
            objects with per-pane customizations (tab color, badge, etc.)

    Returns:
        Dict mapping pane names to iTerm2 sessions

    Raises:
        ValueError: If layout is not recognized
    """
    if layout not in LAYOUT_PANE_NAMES:
        raise ValueError(
            f"Unknown layout: {layout}. Valid: {list(LAYOUT_PANE_NAMES.keys())}"
        )

    # Helper to get customizations for a specific pane
    def get_customization(pane_name: str):
        if profile_customizations:
            return profile_customizations.get(pane_name)
        return None

    # Get the first pane name for the initial window
    first_pane = LAYOUT_PANE_NAMES[layout][0]

    # Create window with initial session (with customizations if provided)
    window = await create_window(
        connection,
        profile=profile,
        profile_customizations=get_customization(first_pane),
    )
    initial_session = window.current_tab.current_session

    panes: dict[str, "iterm2.Session"] = {}

    if layout == "single":
        # Single pane - no splitting needed, just use initial session
        panes["main"] = initial_session

    elif layout == "vertical":
        # Split into left and right
        panes["left"] = initial_session
        panes["right"] = await split_pane(
            initial_session,
            vertical=True,
            profile=profile,
            profile_customizations=get_customization("right"),
        )

    elif layout == "horizontal":
        # Split into top and bottom
        panes["top"] = initial_session
        panes["bottom"] = await split_pane(
            initial_session,
            vertical=False,
            profile=profile,
            profile_customizations=get_customization("bottom"),
        )

    elif layout == "quad":
        # Create 2x2 grid:
        # 1. Split vertically: left | right
        # 2. Split left horizontally: top_left / bottom_left
        # 3. Split right horizontally: top_right / bottom_right
        left = initial_session
        right = await split_pane(
            left,
            vertical=True,
            profile=profile,
            profile_customizations=get_customization("top_right"),
        )

        # Split the left column
        panes["top_left"] = left
        panes["bottom_left"] = await split_pane(
            left,
            vertical=False,
            profile=profile,
            profile_customizations=get_customization("bottom_left"),
        )

        # Split the right column
        panes["top_right"] = right
        panes["bottom_right"] = await split_pane(
            right,
            vertical=False,
            profile=profile,
            profile_customizations=get_customization("bottom_right"),
        )

    elif layout == "triple_vertical":
        # Create 3 vertical panes: left | middle | right
        # 1. Split initial into 2
        # 2. Split right pane into 2 more
        panes["left"] = initial_session
        right_section = await split_pane(
            initial_session,
            vertical=True,
            profile=profile,
            profile_customizations=get_customization("middle"),
        )
        panes["middle"] = right_section
        panes["right"] = await split_pane(
            right_section,
            vertical=True,
            profile=profile,
            profile_customizations=get_customization("right"),
        )

    return panes


async def create_multi_claude_layout(
    connection: "iterm2.Connection",
    projects: dict[str, str],
    layout: str,
    skip_permissions: bool = False,
    project_envs: Optional[dict[str, dict[str, str]]] = None,
    profile: Optional[str] = None,
    profile_customizations: Optional[dict[str, "iterm2.LocalWriteOnlyProfile"]] = None,
    pane_marker_ids: Optional[dict[str, str]] = None,
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
        layout: Layout type (single, vertical, horizontal, quad, triple_vertical)
        skip_permissions: If True, start Claude with --dangerously-skip-permissions
        project_envs: Optional dict mapping pane names to env var dicts. Each
            pane can have its own environment variables set before starting Claude.
        profile: Optional profile name to use for all panes
        profile_customizations: Optional dict mapping pane names to LocalWriteOnlyProfile
            objects with per-pane customizations (tab color, badge, etc.)
        pane_marker_ids: Optional dict mapping pane names to marker IDs for Stop hook
            injection. Each worker will have a Stop hook that logs its marker ID
            to the JSONL for completion detection.

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

    # Create the pane layout with profile customizations
    panes = await create_multi_pane_layout(
        connection,
        layout,
        profile=profile,
        profile_customizations=profile_customizations,
    )

    # Start Claude in all panes in parallel.
    # Each start_claude_in_session call uses wait_for_shell_ready() internally
    # which provides proper readiness detection, so no sleeps between starts needed.
    async def start_claude_for_pane(pane_name: str, project_path: str) -> None:
        session = panes[pane_name]
        pane_env = project_envs.get(pane_name) if project_envs else None
        marker_id = pane_marker_ids.get(pane_name) if pane_marker_ids else None
        await start_claude_in_session(
            session=session,
            project_path=project_path,
            dangerously_skip_permissions=skip_permissions,
            env=pane_env,
            stop_hook_marker_id=marker_id,
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
    managed_session_ids: Optional[set[str]] = None,
) -> Optional[tuple["iterm2.Window", "iterm2.Tab", "iterm2.Session"]]:
    """
    Find a window with an available tab that has room for more panes.

    Searches terminal windows for a tab with fewer than max_panes sessions.
    If managed_session_ids is provided, only considers windows that contain
    at least one managed session (to avoid splitting into user's unrelated windows).

    Args:
        app: iTerm2 app object
        max_panes: Maximum panes before considering a tab full (default 4)
        managed_session_ids: Optional set of iTerm2 session IDs that are managed
            by claude-team. If provided, only windows containing at least one
            of these sessions will be considered.

    Returns:
        Tuple of (window, tab, session) if found, None if all tabs are full
    """
    for window in app.terminal_windows:
        # If we have managed session IDs, check if this window contains any
        if managed_session_ids is not None:
            window_has_managed_session = False
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id in managed_session_ids:
                        window_has_managed_session = True
                        break
                if window_has_managed_session:
                    break
            if not window_has_managed_session:
                # Skip this window - it doesn't contain any managed sessions
                continue

        # Check if any tab has room for more panes
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


