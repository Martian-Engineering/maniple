"""
iTerm2 Utilities for Claude Team MCP

Low-level primitives for iTerm2 terminal control, extracted and adapted
from the original primitives.py for use in the MCP server.
"""

import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from iterm2.app import App as ItermApp
    from iterm2.connection import Connection as ItermConnection
    from iterm2.profile import LocalWriteOnlyProfile as ItermLocalWriteOnlyProfile
    from iterm2.session import Session as ItermSession
    from iterm2.tab import Tab as ItermTab
    from iterm2.window import Window as ItermWindow

    from .cli_backends import AgentCLI

from .subprocess_cache import cached_system_profiler

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

async def send_text(session: "ItermSession", text: str) -> None:
    """
    Send raw text to an iTerm2 session.

    Note: This sends characters as-is. Use send_key() for special keys.
    """
    await session.async_send_text(text)


async def send_key(session: "ItermSession", key: str) -> None:
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


async def send_prompt(session: "ItermSession", text: str, submit: bool = True) -> None:
    """
    Send a prompt to an iTerm2 session, optionally submitting it.

    IMPORTANT: Uses \\x0d (Ctrl+M) for Enter, not \\n.
    iTerm2 interprets \\x0d as the actual Enter keypress.

    For multi-line text, iTerm2 uses bracketed paste mode which wraps the
    content in escape sequences. A delay is needed after pasting multi-line
    content before sending Enter to ensure the paste operation completes.
    The delay scales with text length since longer pastes take more time
    for the terminal to process.

    Note: This function is primarily for Claude Code. For Codex, use
    send_prompt_for_agent() which provides the longer pre-Enter delay
    that Codex requires.

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


# Pre-Enter delay for Codex (in seconds).
# Codex uses crossterm in raw mode - batch text sending works fine,
# but it needs a longer delay before Enter than Claude does.
# Testing showed 200ms is reliable; 50ms (Claude's default) is too short.
CODEX_PRE_ENTER_DELAY = 0.5  # 500ms minimum for Codex input processing


async def send_prompt_for_agent(
    session: "ItermSession",
    text: str,
    agent_type: str = "claude",
    submit: bool = True,
) -> None:
    """
    Send a prompt to an iTerm2 session, with agent-specific input handling.

    Both Claude and Codex handle batch/burst text input correctly. The key
    difference is the delay needed before pressing Enter:

    - **Claude Code**: 50ms delay before Enter is sufficient.
    - **Codex**: Needs ~250ms delay before Enter for reliable input processing.

    Args:
        session: iTerm2 session object
        text: The text to send
        agent_type: The agent type identifier ("claude" or "codex")
        submit: If True, press Enter after sending text
    """
    import asyncio

    if agent_type == "codex":
        # Codex: batch send text, but use longer pre-Enter delay.
        # For long/multi-line prompts, iTerm2's bracketed paste mode needs
        # time to complete before Enter is sent. Use the same delay
        # calculation as send_prompt() but ensure at least CODEX_PRE_ENTER_DELAY.
        await session.async_send_text(text)
        if submit:
            # Calculate delay based on text length (same as send_prompt)
            line_count = text.count("\n")
            char_count = len(text)
            if line_count > 0:
                paste_delay = min(2.0, 0.1 + (line_count * 0.01) + (char_count / 1000 * 0.05))
            else:
                paste_delay = 0.05
            # Use whichever is larger: paste delay or Codex minimum
            delay = max(CODEX_PRE_ENTER_DELAY, paste_delay)
            logger.debug(
                "send_prompt_for_agent: codex chars=%d lines=%d delay=%.3fs",
                char_count, line_count, delay
            )
            await asyncio.sleep(delay)
            await session.async_send_text(KEYS["enter"])
    else:
        # Claude Code and other agents: use standard send_prompt
        await send_prompt(session, text, submit=submit)


async def read_screen(session: "ItermSession") -> list[str]:
    """
    Read all lines from an iTerm2 session's screen.

    Args:
        session: iTerm2 session object

    Returns:
        List of strings, one per line
    """
    screen = await session.async_get_screen_contents()
    return [screen.line(i).string for i in range(screen.number_of_lines)]


async def read_screen_text(session: "ItermSession") -> str:
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
        # Use cached system_profiler to avoid repeated slow calls
        stdout = cached_system_profiler("SPDisplaysDataType")
        if stdout is None:
            logger.warning("system_profiler failed, using default frame")
            return (0.0, 25.0, 1400.0, 900.0)

        # Parse resolution from output like "Resolution: 3840 x 2160"
        match = re.search(r"Resolution: (\d+) x (\d+)", stdout)
        if not match:
            logger.warning("Could not parse screen resolution, using defaults")
            return (0.0, 25.0, 1400.0, 900.0)

        screen_w, screen_h = int(match.group(1)), int(match.group(2))

        # Detect Retina display (2x scale factor)
        scale = 2 if "Retina" in stdout else 1
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

    except Exception as e:
        logger.warning(f"Failed to calculate screen frame: {e}")
        return (0.0, 25.0, 1400.0, 900.0)


async def create_window(
    connection: "ItermConnection",
    profile: Optional[str] = None,
    profile_customizations: Optional["ItermLocalWriteOnlyProfile"] = None,
) -> "ItermWindow":
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
    from iterm2.util import Frame, Point, Size
    from iterm2.window import Window

    # Create the window
    # Build kwargs conditionally - only include profile if explicitly set,
    # otherwise let iTerm2 use its default. Empty string causes INVALID_PROFILE_NAME.
    kwargs: dict = {}
    if profile is not None:
        kwargs["profile"] = profile
    if profile_customizations is not None:
        kwargs["profile_customizations"] = profile_customizations

    window = await Window.async_create(connection, **kwargs)

    if window is None:
        raise RuntimeError("Failed to create iTerm2 window")

    # Exit fullscreen mode if the window opened in fullscreen
    # (can happen if user's default profile or iTerm2 settings use fullscreen)
    is_fullscreen = await window.async_get_fullscreen()
    if is_fullscreen:
        logger.info("Window opened in fullscreen, exiting fullscreen mode")
        await window.async_set_fullscreen(False)
        # Give macOS time to animate out of fullscreen (animation is ~0.2s)
        import asyncio
        await asyncio.sleep(0.2)

    # Set window frame to fill screen without triggering fullscreen mode
    x, y, width, height = _calculate_screen_frame()
    frame = Frame(
        origin=Point(int(x), int(y)),
        size=Size(int(width), int(height)),
    )
    await window.async_set_frame(frame)

    # Bring window to focus
    await window.async_activate()

    return window


async def split_pane(
    session: "ItermSession",
    vertical: bool = True,
    before: bool = False,
    profile: Optional[str] = None,
    profile_customizations: Optional["ItermLocalWriteOnlyProfile"] = None,
) -> "ItermSession":
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
    # Build kwargs conditionally - only include profile if explicitly set
    kwargs: dict = {"vertical": vertical, "before": before}
    if profile is not None:
        kwargs["profile"] = profile
    if profile_customizations is not None:
        kwargs["profile_customizations"] = profile_customizations

    return await session.async_split_pane(**kwargs)


async def close_pane(session: "ItermSession", force: bool = False) -> bool:
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

# Marker used to detect shell readiness - must be unique enough not to appear randomly
SHELL_READY_MARKER = "CLAUDE_TEAM_READY_7f3a9c"


async def wait_for_shell_ready(
    session: "ItermSession",
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.1,
) -> bool:
    """
    Wait for the shell to be ready to accept input.

    Sends an echo command with a unique marker and waits for it to appear
    in the terminal output. This proves the shell is accepting and executing
    commands, regardless of prompt style.

    Args:
        session: iTerm2 session to monitor
        timeout_seconds: Maximum time to wait for shell readiness
        poll_interval: Time between screen content checks

    Returns:
        True if shell became ready, False if timeout was reached
    """
    import asyncio
    import time

    # Send the marker command
    await send_prompt(session, f'echo "{SHELL_READY_MARKER}"')

    # Wait for marker to appear in output (not in the command itself)
    # We look for the marker at the start of a line, which indicates the echo
    # actually executed and produced output, not just that the command was displayed
    start_time = time.monotonic()
    while (time.monotonic() - start_time) < timeout_seconds:
        try:
            content = await read_screen_text(session)
            # Check each line - the output will be the marker on its own line
            # (not preceded by 'echo "' which would be the command)
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped == SHELL_READY_MARKER:
                    return True
        except Exception:
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
    session: "ItermSession",
    timeout_seconds: float = 15.0,
    poll_interval: float = 0.2,
    stable_count: int = 2,
) -> bool:
    """
    Wait for Claude Code's TUI to be ready to accept input.

    Polls the screen content and waits for Claude's prompt to appear.
    Claude is considered ready when the screen shows either:
    - A line starting with '>' (Claude's input prompt)
    - A status line containing 'tokens' (bottom status bar)

    Args:
        session: iTerm2 session to monitor
        timeout_seconds: Maximum time to wait for Claude readiness
        poll_interval: Time between screen content checks
        stable_count: Number of consecutive stable reads before considering ready

    Returns:
        True if Claude became ready, False if timeout was reached
    """
    import asyncio
    import time

    start_time = time.monotonic()
    last_content = None
    stable_reads = 0

    while (time.monotonic() - start_time) < timeout_seconds:
        try:
            content = await read_screen_text(session)
            lines = content.split('\n')

            # Check if content is stable (same as last read)
            if content == last_content:
                stable_reads += 1
            else:
                stable_reads = 0
                last_content = content

            # Only check for Claude readiness after content has stabilized
            if stable_reads >= stable_count:
                for line in lines:
                    stripped = line.strip()
                    # Check for Claude's input prompt (starts with >)
                    if stripped.startswith('>'):
                        logger.debug("Claude ready: found '>' prompt")
                        return True
                    # Check for status bar (contains 'tokens')
                    if 'tokens' in stripped:
                        logger.debug("Claude ready: found status bar with 'tokens'")
                        return True

        except Exception as e:
            # Screen read failed, retry
            logger.debug(f"Screen read failed during Claude ready check: {e}")

        await asyncio.sleep(poll_interval)

    logger.warning(f"Timeout waiting for Claude TUI readiness ({timeout_seconds}s)")
    return False


async def wait_for_agent_ready(
    session: "ItermSession",
    cli: "AgentCLI",
    timeout_seconds: float = 15.0,
    poll_interval: float = 0.2,
    stable_count: int = 2,
) -> bool:
    """
    Wait for an agent CLI to be ready to accept input.

    Generic version of wait_for_claude_ready() that uses the CLI's ready_patterns.
    Polls the screen content and waits for any of the CLI's ready patterns to appear.

    Args:
        session: iTerm2 session to monitor
        cli: The AgentCLI instance providing ready_patterns
        timeout_seconds: Maximum time to wait for readiness
        poll_interval: Time between screen content checks
        stable_count: Number of consecutive stable reads before considering ready

    Returns:
        True if agent became ready, False if timeout was reached
    """
    import asyncio
    import time

    patterns = cli.ready_patterns()
    start_time = time.monotonic()
    last_content = None
    stable_reads = 0

    while (time.monotonic() - start_time) < timeout_seconds:
        try:
            content = await read_screen_text(session)
            lines = content.split('\n')

            # Check if content is stable (same as last read)
            if content == last_content:
                stable_reads += 1
            else:
                stable_reads = 0
                last_content = content

            # Only check for readiness after content has stabilized
            if stable_reads >= stable_count:
                for line in lines:
                    stripped = line.strip()
                    for pattern in patterns:
                        if pattern in stripped:
                            logger.debug(
                                f"Agent ready: found pattern '{pattern}' in line"
                            )
                            return True

        except Exception as e:
            # Screen read failed, retry
            logger.debug(f"Screen read failed during agent ready check: {e}")

        await asyncio.sleep(poll_interval)

    logger.warning(
        f"Timeout waiting for {cli.engine_id} readiness ({timeout_seconds}s)"
    )
    return False


# =============================================================================
# Agent Session Control
# =============================================================================


def build_stop_hook_settings_file(marker_id: str) -> str:
    """
    Build a settings file for Stop hook injection.

    The hook embeds a marker in the command text itself, which gets logged
    to the JSONL in the stop_hook_summary's hookInfos array. This provides
    reliable completion detection without needing stderr or exit code hacks.

    We write to a file instead of passing JSON inline due to a bug in Claude Code
    v2.0.72+ where inline JSON causes the file watcher to incorrectly watch the
    temp directory, crashing on Unix sockets. See:
    https://github.com/anthropics/claude-code/issues/14438

    Args:
        marker_id: Unique ID to embed in the marker (typically session_id)

    Returns:
        Path to the settings file (suitable for --settings flag)
    """
    import json
    from pathlib import Path

    # Use a stable directory that won't have Unix sockets
    settings_dir = Path.home() / ".claude" / "claude-team-settings"
    settings_dir.mkdir(parents=True, exist_ok=True)

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

    # Use marker_id as filename for deterministic, reusable files
    settings_file = settings_dir / f"worker-{marker_id}.json"
    settings_file.write_text(json.dumps(settings, indent=2))

    return str(settings_file)


async def start_agent_in_session(
    session: "ItermSession",
    cli: "AgentCLI",
    project_path: str,
    dangerously_skip_permissions: bool = False,
    env: Optional[dict[str, str]] = None,
    shell_ready_timeout: float = 10.0,
    agent_ready_timeout: float = 30.0,
    stop_hook_marker_id: Optional[str] = None,
    output_capture_path: Optional[str] = None,
) -> None:
    """
    Start an agent CLI in an existing iTerm2 session.

    Changes to the project directory and launches the agent in a single
    atomic command (cd && <agent>). Waits for shell readiness before sending
    the command, then waits for the agent's ready patterns to appear.

    Args:
        session: iTerm2 session to use
        cli: AgentCLI instance defining command and arguments
        project_path: Directory to run the agent in
        dangerously_skip_permissions: If True, add skip-permissions flag
        env: Optional dict of environment variables to set before running agent
        shell_ready_timeout: Max seconds to wait for shell prompt
        agent_ready_timeout: Max seconds to wait for agent to start
        stop_hook_marker_id: If provided, inject a Stop hook for completion detection
            (only used if cli.supports_settings_file() returns True)
        output_capture_path: If provided, capture agent's stdout/stderr to this file
            using tee. Useful for agents that output JSONL for idle detection.

    Raises:
        RuntimeError: If shell not ready or agent fails to start within timeout
    """
    # Wait for shell to be ready
    shell_ready = await wait_for_shell_ready(session, timeout_seconds=shell_ready_timeout)
    if not shell_ready:
        raise RuntimeError(
            f"Shell not ready after {shell_ready_timeout}s in {project_path}. "
            "Terminal may still be initializing."
        )

    # Build settings file for Stop hook injection if supported
    settings_file = None
    if stop_hook_marker_id and cli.supports_settings_file():
        settings_file = build_stop_hook_settings_file(stop_hook_marker_id)

    # Build the full command using the AgentCLI abstraction
    agent_cmd = cli.build_full_command(
        dangerously_skip_permissions=dangerously_skip_permissions,
        settings_file=settings_file,
        env_vars=env,
    )

    # Add output capture via tee if requested
    # This pipes stdout/stderr to both the terminal and a file (for JSONL parsing)
    if output_capture_path:
        agent_cmd = f"{agent_cmd} 2>&1 | tee {output_capture_path}"

    # Combine cd and agent into atomic command to avoid race condition.
    # Shell executes "cd /path && agent" as a unit - if cd fails, agent won't run.
    cmd = f"cd {project_path} && {agent_cmd}"
    
    logger.info(f"start_agent_in_session: Running command: {cmd[:200]}...")

    await send_prompt(session, cmd)

    # Wait for agent to actually start (detect ready patterns, not blind sleep)
    if not await wait_for_agent_ready(
        session, cli, timeout_seconds=agent_ready_timeout
    ):
        raise RuntimeError(
            f"{cli.engine_id} failed to start in {project_path} within "
            f"{agent_ready_timeout}s. Check that '{cli.command()}' command is "
            "available and authentication is configured."
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
    connection: "ItermConnection",
    layout: str,
    profile: Optional[str] = None,
    profile_customizations: Optional[dict[str, "ItermLocalWriteOnlyProfile"]] = None,
) -> dict[str, "ItermSession"]:
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
    current_tab = window.current_tab
    if current_tab is None:
        raise RuntimeError("Failed to get current tab from new window")
    initial_session = current_tab.current_session
    if initial_session is None:
        raise RuntimeError("Failed to get initial session from new window")

    panes: dict[str, "ItermSession"] = {}

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
    connection: "ItermConnection",
    projects: dict[str, str],
    layout: str,
    skip_permissions: bool = False,
    project_envs: Optional[dict[str, dict[str, str]]] = None,
    profile: Optional[str] = None,
    profile_customizations: Optional[dict[str, "ItermLocalWriteOnlyProfile"]] = None,
    pane_marker_ids: Optional[dict[str, str]] = None,
) -> dict[str, "ItermSession"]:
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

    from .cli_backends import claude_cli

    # Start Claude in all panes in parallel.
    # start_agent_in_session uses wait_for_shell_ready() internally, so no sleeps needed.
    async def start_claude_for_pane(pane_name: str, project_path: str) -> None:
        session = panes[pane_name]
        pane_env = project_envs.get(pane_name) if project_envs else None
        marker_id = pane_marker_ids.get(pane_name) if pane_marker_ids else None
        await start_agent_in_session(
            session=session,
            cli=claude_cli,
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


def count_panes_in_tab(tab: "ItermTab") -> int:
    """
    Count the number of panes (sessions) in a tab.

    Args:
        tab: iTerm2 tab object

    Returns:
        Number of sessions in the tab
    """
    return len(tab.sessions)


def count_panes_in_window(window: "ItermWindow") -> int:
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
    app: "ItermApp",
    max_panes: int = MAX_PANES_PER_TAB,
    managed_session_ids: Optional[set[str]] = None,
) -> Optional[tuple["ItermWindow", "ItermTab", "ItermSession"]]:
    """
    Find a window with an available tab that has room for more panes.

    Searches terminal windows for a tab with fewer than max_panes sessions.
    If managed_session_ids is provided, only considers tabs that contain
    at least one managed session (to avoid splitting into user's unrelated tabs).

    Note: When managed_session_ids is an empty set, no tabs will match (correct
    behavior - an empty registry means we have no managed sessions to reuse,
    so a new window should be created).

    Args:
        app: iTerm2 app object
        max_panes: Maximum panes before considering a tab full (default 4)
        managed_session_ids: Optional set of iTerm2 session IDs that are managed
            by claude-team. If provided (including empty set), only tabs
            containing at least one of these sessions will be considered.
            Pass None to consider all tabs.

    Returns:
        Tuple of (window, tab, session) if found, None if all tabs are full
    """
    for window in app.terminal_windows:
        for tab in window.tabs:
            # If we have managed session IDs filter, check if this tab contains any
            # Note: empty set is valid (matches nothing) - use `is not None` check
            if managed_session_ids is not None:
                tab_has_managed = any(
                    s.session_id in managed_session_ids for s in tab.sessions
                )
                if not tab_has_managed:
                    # Skip this tab - it doesn't contain any managed sessions
                    continue

            # Check if this tab has room for more panes
            if count_panes_in_tab(tab) < max_panes:
                # Return the current session in this tab as the split target
                current_session = tab.current_session
                if current_session:
                    return (window, tab, current_session)
    return None


async def get_window_for_session(
    app: "ItermApp",
    session: "ItermSession",
) -> Optional["ItermWindow"]:
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

