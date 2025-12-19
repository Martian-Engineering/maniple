"""
Claude Team MCP Server

FastMCP-based server for managing multiple Claude Code sessions via iTerm2.
Allows a "manager" Claude Code session to spawn and coordinate multiple
"worker" Claude Code sessions.
"""

import asyncio
import hashlib
import logging
import os
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .colors import generate_tab_color
from .formatting import format_badge_text, format_session_title
from .iterm_utils import (
    LAYOUT_PANE_NAMES,
    MAX_PANES_PER_TAB,
    count_panes_in_tab,
    create_multi_claude_layout,
    create_window,
    find_available_window,
    read_screen_text,
    send_prompt,
    split_pane,
    start_claude_in_session,
)
from .names import pick_names_for_count
from .profile import PROFILE_NAME, get_or_create_profile
from .registry import SessionRegistry, SessionStatus, TaskInfo
from .task_completion import (
    TaskStatus,
    detect_completion,
    wait_for_completion as wait_for_completion_impl,
)
from .worker_prompt import generate_worker_prompt, get_coordinator_guidance
from .worktree import WorktreeError, create_worktree, remove_worktree

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("claude-team-mcp")


# =============================================================================
# Error Response Helpers
# =============================================================================


def error_response(
    message: str,
    hint: str | None = None,
    **extra_fields,
) -> dict:
    """
    Create a standardized error response with optional recovery hint.

    Args:
        message: The error message describing what went wrong
        hint: Actionable instructions for recovery (optional)
        **extra_fields: Additional fields to include in the response

    Returns:
        Dict with 'error', optional 'hint', and any extra fields
    """
    result = {"error": message}
    if hint:
        result["hint"] = hint
    result.update(extra_fields)
    return result


# Common hints for reusable error scenarios
HINTS = {
    "session_not_found": (
        "Run list_sessions to see available sessions, or discover_sessions "
        "to find orphaned iTerm2 sessions that can be imported"
    ),
    "project_path_missing": (
        "Verify the path exists. For git worktrees, check 'git worktree list'. "
        "Use an absolute path like '/Users/name/project'"
    ),
    "iterm_connection": (
        "Ensure iTerm2 is running and Python API is enabled: "
        "iTerm2 → Preferences → General → Magic → Enable Python API"
    ),
    "registry_empty": (
        "No sessions are being managed. Use spawn_team to create a new session, "
        "or discover_sessions to find existing Claude sessions in iTerm2"
    ),
    "split_session_not_found": (
        "The split_from_session ID was not found. Run list_sessions to see "
        "available sessions to split from, or omit split_from_session to "
        "split from the currently active iTerm window"
    ),
    "no_jsonl_file": (
        "Claude may not have started yet or the session file doesn't exist. "
        "Wait a few seconds and try again, or check that Claude Code started "
        "successfully in the terminal"
    ),
    "session_closed": (
        "This session has been closed. Use spawn_team to create a new one, "
        "or list_sessions to find other active sessions"
    ),
    "no_active_task": (
        "No task is being tracked for this session. Use send_message with "
        "track_task=True to start tracking a task for completion detection"
    ),
    "project_path_detection_failed": (
        "Could not auto-detect project path from terminal. Provide project_path "
        "explicitly when calling import_session"
    ),
    "session_busy": (
        "The session is currently processing. Wait for it to finish, or use "
        "force=True to close it anyway (may lose work)"
    ),
}


# =============================================================================
# Worktree Detection
# =============================================================================


def get_worktree_beads_dir(project_path: str) -> str | None:
    """
    Detect if project_path is a git worktree and return the main repo's .beads dir.

    Git worktrees have .git as a file (not a directory) pointing to the main repo.
    The `git rev-parse --git-common-dir` command returns the path to the shared
    .git directory, which we can use to find the main repo.

    Args:
        project_path: Absolute path to the project directory

    Returns:
        Path to the main repo's .beads directory if:
        - project_path is a git worktree
        - The main repo has a .beads directory
        Otherwise returns None.
    """
    try:
        # Run git rev-parse --git-common-dir to get the shared .git directory
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            # Not a git repo or git command failed
            return None

        git_common_dir = result.stdout.strip()

        # If the result is just ".git", this is the main repo (not a worktree)
        if git_common_dir == ".git":
            return None

        # git_common_dir is the path to the shared .git directory
        # The main repo is the parent of .git
        # Handle both absolute and relative paths
        if not os.path.isabs(git_common_dir):
            git_common_dir = os.path.join(project_path, git_common_dir)

        git_common_dir = os.path.normpath(git_common_dir)

        # Main repo is the parent directory of .git
        main_repo = os.path.dirname(git_common_dir)

        # Check if the main repo has a .beads directory
        beads_dir = os.path.join(main_repo, ".beads")
        if os.path.isdir(beads_dir):
            logger.info(
                f"Detected git worktree. Setting BEADS_DIR={beads_dir} "
                f"for project {project_path}"
            )
            return beads_dir

        return None

    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout checking git worktree status for {project_path}")
        return None
    except Exception as e:
        logger.warning(f"Error checking git worktree status for {project_path}: {e}")
        return None


# =============================================================================
# Application Context
# =============================================================================


@dataclass
class AppContext:
    """
    Application context shared across all tool invocations.

    Maintains the iTerm2 connection and registry of managed sessions.
    This is the persistent state that makes the MCP server useful.
    """

    iterm_connection: object  # iterm2.Connection
    iterm_app: object  # iterm2.App
    registry: SessionRegistry


# =============================================================================
# Lifespan Management
# =============================================================================


async def refresh_iterm_connection() -> tuple["iterm2.Connection", "iterm2.App"]:
    """
    Create a fresh iTerm2 connection.

    The iTerm2 Python API uses websockets with ping_interval=None, meaning
    connections can go stale without any keepalive mechanism. This function
    creates a new connection when needed.

    Returns:
        Tuple of (connection, app)

    Raises:
        RuntimeError: If connection fails
    """
    import iterm2

    logger.debug("Creating fresh iTerm2 connection...")
    try:
        connection = await iterm2.Connection.async_create()
        app = await iterm2.async_get_app(connection)
        logger.debug("Fresh iTerm2 connection established")
        return connection, app
    except Exception as e:
        logger.error(f"Failed to refresh iTerm2 connection: {e}")
        raise RuntimeError("Could not connect to iTerm2") from e


async def ensure_connection(app_ctx: "AppContext") -> tuple["iterm2.Connection", "iterm2.App"]:
    """
    Ensure we have a working iTerm2 connection, refreshing if stale.

    The iTerm2 websocket connection can go stale due to lack of keepalive
    (ping_interval=None in the iterm2 library). This function tests the
    connection and refreshes it if needed.

    Args:
        app_ctx: The application context containing connection and app

    Returns:
        Tuple of (connection, app) - either existing or refreshed
    """
    import iterm2

    connection = app_ctx.iterm_connection
    app = app_ctx.iterm_app

    # Test if connection is still alive by trying a simple operation
    try:
        # async_get_app is a lightweight call that tests the connection
        app = await iterm2.async_get_app(connection)
        return connection, app
    except Exception as e:
        logger.warning(f"iTerm2 connection appears stale ({e}), refreshing...")
        # Connection is dead, create a new one
        connection, app = await refresh_iterm_connection()
        # Update the context with fresh connection
        app_ctx.iterm_connection = connection
        app_ctx.iterm_app = app
        return connection, app


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Manage iTerm2 connection lifecycle.

    Connects to iTerm2 on startup and maintains the connection
    for the duration of the server's lifetime.

    Note: The iTerm2 Python API uses websockets with ping_interval=None,
    meaning connections can go stale. Individual tool functions should use
    ensure_connection() before making iTerm2 API calls that use the
    connection directly.
    """
    logger.info("Claude Team MCP Server starting...")

    # Import iterm2 here to fail fast if not available
    try:
        import iterm2
    except ImportError as e:
        logger.error(
            "iterm2 package not found. Install with: uv add iterm2\n"
            "Also enable: iTerm2 → Preferences → General → Magic → Enable Python API"
        )
        raise RuntimeError("iterm2 package required") from e

    # Connect to iTerm2
    logger.info("Connecting to iTerm2...")
    try:
        connection = await iterm2.Connection.async_create()
        app = await iterm2.async_get_app(connection)
        logger.info("Connected to iTerm2 successfully")
    except Exception as e:
        logger.error(f"Failed to connect to iTerm2: {e}")
        logger.error("Make sure iTerm2 is running and Python API is enabled")
        raise RuntimeError("Could not connect to iTerm2") from e

    # Create application context with session registry
    ctx = AppContext(
        iterm_connection=connection,
        iterm_app=app,
        registry=SessionRegistry(),
    )

    try:
        yield ctx
    finally:
        # Cleanup: close any remaining sessions gracefully
        logger.info("Claude Team MCP Server shutting down...")
        if ctx.registry.count() > 0:
            logger.info(f"Cleaning up {ctx.registry.count()} managed session(s)...")
        logger.info("Shutdown complete")


# =============================================================================
# FastMCP Server
# =============================================================================

mcp = FastMCP(
    "Claude Team Manager",
    lifespan=app_lifespan,
)


# =============================================================================
# Tool Implementations (Placeholders - will be implemented in separate tasks)
# =============================================================================


@mcp.tool()
async def spawn_team(
    ctx: Context[ServerSession, AppContext],
    projects: dict[str, str],
    layout: str = "auto",
    skip_permissions: bool = False,
    custom_names: list[str] | None = None,
    custom_prompt: str | None = None,
    include_beads_instructions: bool = True,
    use_worktrees: bool = False,
) -> dict:
    """
    Spawn multiple Claude Code sessions in a multi-pane layout.

    Creates a new iTerm2 window with the specified pane layout and starts
    Claude Code in each pane. All sessions are registered for management.
    Each pane receives a unique tab color from a visually distinct sequence,
    and badges display iconic names (e.g., "Groucho", "John").

    **Two Modes:**

    1. **Standard Mode** (default, custom_prompt=None):
       - Sends a pre-built worker pre-prompt to each session explaining
         the coordination workflow (blocker flagging, beads discipline, etc.)
       - Returns `coordinator_guidance` with instructions for the coordinator
       - Best for general-purpose coordinated work

    2. **Custom Mode** (custom_prompt provided):
       - Sends your custom_prompt to each worker instead of the standard pre-prompt
       - If include_beads_instructions=True, appends beads guidance to your prompt
       - Does NOT return coordinator_guidance (you're in charge of the workflow)
       - Best for specialized workflows or when workers need specific instructions

    Args:
        projects: Dict mapping pane names to project paths. Keys must match
            the layout's pane names:
            - "single": ["main"]
            - "vertical": ["left", "right"]
            - "horizontal": ["top", "bottom"]
            - "quad": ["top_left", "top_right", "bottom_left", "bottom_right"]
            - "triple_vertical": ["left", "middle", "right"]
        layout: Layout type - "auto" (default), "single", "vertical", "horizontal",
            "quad", or "triple_vertical". When "auto", the layout is selected based
            on project count:
            - 1 project: "single" (full window, no splits)
            - 2 projects: "vertical"
            - 3 projects: "triple_vertical"
            - 4+ projects: "quad"
        skip_permissions: If True, start Claude with --dangerously-skip-permissions
        custom_names: (Optional) Override automatic name selection with explicit names.
            Leave empty to auto-select a size-matched iconic group (e.g., Beatles for 4,
            Three Stooges for 3, Simon & Garfunkel for 2).
        custom_prompt: If provided, sends this prompt to workers instead of the
            standard pre-prompt (activates custom mode).
        include_beads_instructions: For custom mode only - if True (default),
            appends beads quick reference to your custom prompt.
        use_worktrees: If True, create an isolated git worktree for each worker.
            Workers will operate in their own working directory while sharing
            the same repository history. Each worker gets a branch named
            "{worker_name}-{hash}" (e.g., "Mark-a1b2c3") for uniqueness.

    Returns:
        Dict with:
            - sessions: Dict mapping pane names to session info (id, status, project_path,
              worktree_path if use_worktrees=True)
            - layout: The layout used (resolved from "auto" if applicable)
            - count: Number of sessions created
            - name_set: The name set used (or "custom" if custom_names provided)
            - mode: "standard" or "custom"
            - use_worktrees: Whether worktrees were created
            - coordinator_guidance: Instructions for the coordinator (standard mode only)

    Example (standard mode):
        spawn_team(
            projects={
                "left": "/path/to/frontend",
                "right": "/path/to/backend",
            },
            layout="vertical",
        )
        # Automatically picks a duo like Simon & Garfunkel or Tom & Jerry
        # Returns coordinator_guidance with worker management instructions

    Example (custom mode):
        spawn_team(
            projects={"main": "/path/to/project"},
            layout="single",
            custom_prompt="You are a code reviewer. Review all changed files.",
            include_beads_instructions=False  # Skip beads for this workflow
        )
        # Workers receive your custom prompt, no coordinator_guidance returned
    """
    import iterm2

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Ensure we have a fresh connection (websocket can go stale)
    connection, _ = await ensure_connection(app_ctx)

    # Auto-select layout based on project count
    if layout == "auto":
        count = len(projects)
        if count == 1:
            layout = "single"  # full window, no splits
        elif count == 2:
            layout = "vertical"
        elif count == 3:
            layout = "triple_vertical"
        elif count >= 4:
            layout = "quad"

    # Validate layout
    if layout not in LAYOUT_PANE_NAMES:
        return error_response(
            f"Invalid layout: {layout}",
            hint=f"Valid layouts are: {', '.join(LAYOUT_PANE_NAMES.keys())}",
        )

    # Validate pane names
    expected_panes = set(LAYOUT_PANE_NAMES[layout])
    provided_panes = set(projects.keys())
    if not provided_panes.issubset(expected_panes):
        invalid = provided_panes - expected_panes
        return error_response(
            f"Invalid pane names for layout '{layout}': {list(invalid)}",
            hint=f"Valid pane names for '{layout}' are: {', '.join(expected_panes)}",
        )

    # Validate all project paths exist and detect worktrees
    resolved_projects = {}
    project_envs: dict[str, dict[str, str]] = {}
    for pane_name, project_path in projects.items():
        resolved = os.path.abspath(os.path.expanduser(project_path))
        if not os.path.isdir(resolved):
            return error_response(
                f"Project path does not exist for '{pane_name}': {resolved}",
                hint=HINTS["project_path_missing"],
            )
        resolved_projects[pane_name] = resolved

        # Check for worktree and set BEADS_DIR if needed
        beads_dir = get_worktree_beads_dir(resolved)
        if beads_dir:
            project_envs[pane_name] = {"BEADS_DIR": beads_dir}

    try:
        # Ensure the claude-team profile exists
        await get_or_create_profile(connection)

        # Get base session index for color generation
        base_index = registry.count()

        # Create profile customizations for each pane
        # Each pane gets a unique color from the sequence and a badge showing iconic name
        pane_customizations: dict[str, iterm2.LocalWriteOnlyProfile] = {}
        layout_pane_names = LAYOUT_PANE_NAMES[layout]

        # Pick iconic names for sessions
        project_count = len(projects)
        if custom_names:
            iconic_names = custom_names
            used_name_set = "custom"
        else:
            # Auto-select a size-matched set based on worker count
            used_name_set, iconic_names = pick_names_for_count(project_count)

        # Map pane names to iconic names (in layout order)
        pane_to_iconic: dict[str, str] = {}
        name_index = 0
        for pane_name in layout_pane_names:
            if pane_name in projects:
                pane_to_iconic[pane_name] = iconic_names[name_index % len(iconic_names)]
                name_index += 1

        # Pre-generate session IDs for each pane
        # These will be used as Stop hook markers and for registry registration
        pane_session_ids: dict[str, str] = {}
        for pane_name in projects:
            pane_session_ids[pane_name] = str(uuid.uuid4())[:8]

        # Create worktrees if requested
        # Track original project paths and worktree paths separately
        original_projects = dict(resolved_projects)  # Preserve original paths
        worktree_paths: dict[str, Path] = {}  # pane_name -> worktree Path

        if use_worktrees:
            for pane_name, project_path in list(resolved_projects.items()):
                worker_name = pane_to_iconic[pane_name]
                # Each worker gets their own branch with a unique hash suffix
                # to avoid conflicts if names are recycled across spawns
                unique_seed = f"{worker_name}-{time.time()}-{pane_name}"
                short_hash = hashlib.sha256(unique_seed.encode()).hexdigest()[:6]
                worker_branch = f"{worker_name}-{short_hash}"
                worktree_dir_name = f"{worker_name}-{short_hash}"
                try:
                    worktree_path = create_worktree(
                        repo_path=Path(project_path),
                        worktree_name=worktree_dir_name,
                        branch=worker_branch,
                    )
                    worktree_paths[pane_name] = worktree_path
                    # Update resolved_projects so Claude starts in the worktree
                    resolved_projects[pane_name] = str(worktree_path)
                    logger.info(f"Created worktree for {worker_name} at {worktree_path}")
                except WorktreeError as e:
                    # Log but don't fail - worker can still use main repo
                    logger.warning(
                        f"Failed to create worktree for {worker_name}: {e}. "
                        "Worker will use main repo."
                    )

        for pane_index, pane_name in enumerate(layout_pane_names):
            if pane_name not in projects:
                continue  # Skip panes not being used

            customization = iterm2.LocalWriteOnlyProfile()

            # Get the iconic name for this pane
            iconic_name = pane_to_iconic[pane_name]

            # Set tab title with iconic name
            tab_title = format_session_title(iconic_name)
            customization.set_name(tab_title)

            # Set unique tab color for this pane
            color = generate_tab_color(base_index + pane_index)
            customization.set_tab_color(color)
            customization.set_use_tab_color(True)

            # Set badge text to show iconic name
            customization.set_badge_text(iconic_name)

            pane_customizations[pane_name] = customization

        # Create the multi-pane layout and start Claude in each pane
        # Pass pre-generated session IDs as marker IDs for Stop hook injection
        pane_sessions = await create_multi_claude_layout(
            connection=connection,
            projects=resolved_projects,
            layout=layout,
            skip_permissions=skip_permissions,
            project_envs=project_envs if project_envs else None,
            profile=PROFILE_NAME,
            pane_customizations=pane_customizations,
            pane_marker_ids=pane_session_ids,
        )

        # Register all sessions (this is quick, no I/O)
        # Use the pre-generated session IDs that were baked into Stop hooks
        managed_sessions = {}
        for pane_name, iterm_session in pane_sessions.items():
            iconic_name = pane_to_iconic[pane_name]
            session_id = pane_session_ids[pane_name]
            # Use resolved_projects which has worktree paths if created
            # Claude creates JSONL based on working directory, so we need
            # to use the worktree path for JSONL lookup to work correctly
            managed = registry.add(
                iterm_session=iterm_session,
                project_path=resolved_projects[pane_name],
                name=iconic_name,  # e.g., "Groucho", "John"
                session_id=session_id,  # Use pre-generated ID from Stop hook
            )
            # Store worktree path if one was created for this session
            if pane_name in worktree_paths:
                managed.worktree_path = worktree_paths[pane_name]
            managed_sessions[pane_name] = managed

        # Send marker messages to all sessions for JSONL correlation
        from .session_state import generate_marker_message

        for pane_name, managed in managed_sessions.items():
            marker_message = generate_marker_message(managed.session_id)
            await send_prompt(pane_sessions[pane_name], marker_message, submit=True)

        # Wait for markers to be logged
        await asyncio.sleep(2)

        # Determine mode and send appropriate prompts to workers
        is_standard_mode = custom_prompt is None

        for pane_name, managed in managed_sessions.items():
            iconic_name = pane_to_iconic[pane_name]

            if is_standard_mode:
                # Standard mode: send worker pre-prompt with coordination workflow
                worker_prompt = generate_worker_prompt(
                    managed.session_id, iconic_name, use_worktree=use_worktrees
                )
            else:
                # Custom mode: use the provided custom_prompt
                worker_prompt = custom_prompt
                if include_beads_instructions:
                    # Append beads guidance from BEADS_HELP_TEXT
                    worker_prompt += "\n\n---\n" + BEADS_HELP_TEXT

            await send_prompt(pane_sessions[pane_name], worker_prompt, submit=True)

        # Wait for prompts to be processed
        await asyncio.sleep(1)

        # Discover Claude sessions by marker and update status
        result_sessions = {}
        for pane_name, managed in managed_sessions.items():
            if not managed.discover_claude_session_by_marker():
                # Fallback to old discovery if marker not found
                logger.warning(
                    f"Marker-based discovery failed for {managed.session_id}, "
                    "falling back to timestamp-based discovery"
                )
                managed.discover_claude_session()
            registry.update_status(managed.session_id, SessionStatus.READY)
            result_sessions[pane_name] = managed.to_dict()

        # Build return value based on mode
        result = {
            "sessions": result_sessions,
            "layout": layout,
            "count": len(result_sessions),
            "name_set": used_name_set,
            "mode": "standard" if is_standard_mode else "custom",
            "use_worktrees": use_worktrees,
        }

        # Include coordinator guidance only in standard mode
        if is_standard_mode:
            result["coordinator_guidance"] = get_coordinator_guidance(use_worktrees)
        else:
            result["coordinator_guidance"] = None

        return result

    except ValueError as e:
        # Layout or pane name validation errors from the primitive
        logger.error(f"Validation error in spawn_team: {e}")
        return error_response(str(e))
    except Exception as e:
        logger.error(f"Failed to spawn team: {e}")
        return error_response(
            str(e),
            hint=HINTS["iterm_connection"],
        )


@mcp.tool()
async def list_sessions(
    ctx: Context[ServerSession, AppContext],
    status_filter: str | None = None,
    blocked_only: bool = False,
) -> list[dict]:
    """
    List all managed Claude Code sessions.

    Returns information about each session including its ID, name,
    project path, and current status. Results are sorted with blocked
    sessions first for coordinator visibility.

    Args:
        status_filter: Optional filter by status - "ready", "busy", "spawning", "closed"
        blocked_only: If True, only return sessions that are currently blocked

    Returns:
        List of session info dicts
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Get sessions, optionally filtered by status
    if status_filter:
        try:
            status = SessionStatus(status_filter)
            sessions = registry.list_by_status(status)
        except ValueError:
            valid_statuses = [s.value for s in SessionStatus]
            return [error_response(
                f"Invalid status filter: {status_filter}",
                hint=f"Valid statuses are: {', '.join(valid_statuses)}",
            )]
    else:
        sessions = registry.list_all()

    # Filter to only blocked sessions if requested
    if blocked_only:
        sessions = [s for s in sessions if s.is_blocked()]

    # Sort with blocked sessions first, then by created_at
    sessions = sorted(sessions, key=lambda s: (not s.is_blocked(), s.created_at))

    # Convert to dicts and add message count if JSONL is available
    results = []
    for session in sessions:
        info = session.to_dict()
        # Try to get conversation stats
        state = session.get_conversation_state()
        if state:
            info["message_count"] = state.message_count
            info["is_processing"] = state.is_processing
        results.append(info)

    return results


@mcp.tool()
async def check_blockers(
    ctx: Context[ServerSession, AppContext],
    session_ids: list[str] | None = None,
) -> dict:
    """
    Scan worker conversations for blocker markers.

    Workers flag blockers by including `<!BLOCKED:reason!>` in their responses.
    This tool scans recent conversation history for these markers.

    Args:
        session_ids: Optional list of session IDs to check. If not provided,
            checks all active sessions.

    Returns:
        Dict with:
            - blockers: List of detected blockers, each containing:
                - session_id: The session ID
                - name: The worker's name
                - reason: The blocker reason from the marker
                - message_uuid: UUID of the message containing the blocker
            - checked_count: Number of sessions scanned
            - blocked_count: Number of sessions with blockers
    """
    import re

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Get sessions to check
    if session_ids:
        sessions = [registry.get(sid) for sid in session_ids]
        sessions = [s for s in sessions if s is not None]
    else:
        sessions = registry.list_all()

    # Pattern to match <!BLOCKED:reason!>
    blocker_pattern = re.compile(r"<!BLOCKED:(.+?)!>", re.DOTALL)

    # Example text from the pre-prompt to ignore
    example_reasons = {
        "reason here",
        "Need API credentials to test authentication flow",
    }

    blockers = []
    for session in sessions:
        state = session.get_conversation_state()
        if not state:
            continue

        # Check recent messages (last 20)
        recent_messages = state.messages[-20:] if state.messages else []
        for msg in recent_messages:
            if msg.role != "assistant":
                continue
            # Message.content is already extracted text
            matches = blocker_pattern.findall(msg.content)
            for reason in matches:
                reason_stripped = reason.strip()
                # Skip examples from the pre-prompt
                if reason_stripped in example_reasons:
                    continue
                blockers.append({
                    "session_id": session.session_id,
                    "name": session.name,
                    "reason": reason_stripped,
                    "message_uuid": msg.uuid,
                })

    return {
        "blockers": blockers,
        "checked_count": len(sessions),
        "blocked_count": len(set(b["session_id"] for b in blockers)),
    }


@mcp.tool()
async def send_message(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    message: str,
    wait_for_response: bool = False,
    timeout: float = 120.0,
    track_task: bool = False,
    task_id: str | None = None,
    beads_issue_id: str | None = None,
) -> dict:
    """
    Send a message to a managed Claude Code session.

    Injects the message into the specified session's terminal and
    optionally waits for Claude's response.

    Args:
        session_id: ID of the target session (from spawn_team or list_sessions)
        message: The prompt/message to send
        wait_for_response: If True, wait for Claude to finish responding
        timeout: Maximum seconds to wait for response (if wait_for_response=True)
        track_task: If True, track this as a delegated task for completion detection
        task_id: Optional custom task ID (auto-generated if track_task=True but not provided)
        beads_issue_id: Optional beads issue ID to link for completion tracking

    Returns:
        Dict with success status and optional response content
    """
    from .session_state import wait_for_response as wait_for_resp

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    # Check session is ready
    if session.status == SessionStatus.CLOSED:
        return error_response(
            f"Session is closed: {session_id}",
            hint=HINTS["session_closed"],
        )

    try:
        # Update status to busy
        registry.update_status(session_id, SessionStatus.BUSY)

        # Capture baseline state before sending (for response detection)
        baseline_uuid = None
        jsonl_path = session.get_jsonl_path()
        if jsonl_path and jsonl_path.exists():
            state = session.get_conversation_state()
            if state and state.last_assistant_message:
                baseline_uuid = state.last_assistant_message.uuid

        # Track task if requested
        task_info = None
        if track_task:
            # Generate task ID if not provided
            import uuid as uuid_module

            actual_task_id = task_id or f"task-{uuid_module.uuid4().hex[:8]}"
            task_info = session.start_task(
                task_id=actual_task_id,
                description=message,
                beads_issue_id=beads_issue_id,
            )

        # Append hint about bd_help tool to help workers understand beads
        message_with_hint = message + WORKER_MESSAGE_HINT

        # Send the message to the terminal
        await send_prompt(session.iterm_session, message_with_hint, submit=True)

        result = {
            "success": True,
            "session_id": session_id,
            "message_sent": message[:100] + "..." if len(message) > 100 else message,
        }

        # Include task info if tracking
        if task_info:
            result["task_id"] = task_info.task_id
            result["task_tracking"] = True

        # Optionally wait for response
        if wait_for_response:
            if jsonl_path and jsonl_path.exists():
                response = await wait_for_resp(
                    jsonl_path=jsonl_path,
                    timeout=timeout,
                    idle_threshold=2.0,
                    baseline_message_uuid=baseline_uuid,
                )
                if response:
                    result["response"] = response.content
                else:
                    result["response"] = None
                    result["timeout"] = True

        # Update status back to ready
        registry.update_status(session_id, SessionStatus.READY)

        return result

    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        registry.update_status(session_id, SessionStatus.READY)
        return error_response(
            str(e),
            hint=HINTS["iterm_connection"],
            session_id=session_id,
        )


@mcp.tool()
async def broadcast_message(
    ctx: Context[ServerSession, AppContext],
    session_ids: list[str],
    message: str,
    wait_for_response: bool = False,
    timeout: float = 120.0,
) -> dict:
    """
    Send the same message to multiple Claude Code sessions in parallel.

    Broadcasts a message to all specified sessions concurrently and returns
    aggregated results. Useful for coordinating multiple worker sessions
    or sending the same instruction to a team.

    Args:
        session_ids: List of session IDs to send the message to
        message: The prompt/message to send to all sessions
        wait_for_response: If True, wait for Claude to finish responding in each session
        timeout: Maximum seconds to wait for responses (if wait_for_response=True)

    Returns:
        Dict with:
            - results: Dict mapping session_id to individual result
            - success_count: Number of sessions that received the message
            - failure_count: Number of sessions that failed
            - total: Total number of sessions targeted
    """
    from .session_state import wait_for_response as wait_for_resp

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    if not session_ids:
        return error_response(
            "No session_ids provided",
            hint=HINTS["registry_empty"],
        )

    # Validate all sessions exist first
    # (fail fast if any session is invalid)
    missing_sessions = []
    closed_sessions = []
    valid_sessions = []

    for sid in session_ids:
        session = registry.get(sid)
        if not session:
            missing_sessions.append(sid)
        elif session.status == SessionStatus.CLOSED:
            closed_sessions.append(sid)
        else:
            valid_sessions.append((sid, session))

    # Report validation errors but continue with valid sessions
    results = {}

    for sid in missing_sessions:
        results[sid] = error_response(
            f"Session not found: {sid}",
            hint=HINTS["session_not_found"],
            success=False,
        )

    for sid in closed_sessions:
        results[sid] = error_response(
            f"Session is closed: {sid}",
            hint=HINTS["session_closed"],
            success=False,
        )

    if not valid_sessions:
        return {
            "results": results,
            "success_count": 0,
            "failure_count": len(results),
            "total": len(session_ids),
            **error_response(
                "No valid sessions to send to",
                hint=HINTS["session_not_found"],
            ),
        }

    async def send_to_session(sid: str, session) -> tuple[str, dict]:
        """
        Send message to a single session.

        Returns tuple of (session_id, result_dict).
        """
        try:
            # Update status to busy
            registry.update_status(sid, SessionStatus.BUSY)

            # Capture baseline state before sending (for response detection)
            baseline_uuid = None
            jsonl_path = session.get_jsonl_path()
            if jsonl_path and jsonl_path.exists():
                state = session.get_conversation_state()
                if state and state.last_assistant_message:
                    baseline_uuid = state.last_assistant_message.uuid

            # Append hint about bd_help tool to help workers understand beads
            message_with_hint = message + WORKER_MESSAGE_HINT

            # Send the message to the terminal
            await send_prompt(session.iterm_session, message_with_hint, submit=True)

            result = {
                "success": True,
                "session_id": sid,
                "message_sent": message[:100] + "..." if len(message) > 100 else message,
            }

            # Optionally wait for response
            if wait_for_response:
                if jsonl_path and jsonl_path.exists():
                    response = await wait_for_resp(
                        jsonl_path=jsonl_path,
                        timeout=timeout,
                        idle_threshold=2.0,
                        baseline_message_uuid=baseline_uuid,
                    )
                    if response:
                        result["response"] = response.content
                    else:
                        result["response"] = None
                        result["timeout"] = True

            # Update status back to ready
            registry.update_status(sid, SessionStatus.READY)

            return (sid, result)

        except Exception as e:
            logger.error(f"Failed to send message to {sid}: {e}")
            registry.update_status(sid, SessionStatus.READY)
            return (sid, error_response(
                str(e),
                hint=HINTS["iterm_connection"],
                session_id=sid,
                success=False,
            ))

    # Send to all valid sessions in parallel
    tasks = [send_to_session(sid, session) for sid, session in valid_sessions]
    parallel_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for item in parallel_results:
        if isinstance(item, Exception):
            # This shouldn't happen since we catch exceptions in send_to_session,
            # but handle it just in case
            logger.error(f"Unexpected exception in broadcast: {item}")
            continue
        sid, result = item
        results[sid] = result

    # Compute success/failure counts
    success_count = sum(1 for r in results.values() if r.get("success", False))
    failure_count = len(results) - success_count

    return {
        "results": results,
        "success_count": success_count,
        "failure_count": failure_count,
        "total": len(session_ids),
    }


@mcp.tool()
async def get_response(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    wait: bool = True,
    timeout: float = 60.0,
) -> dict:
    """
    Get the latest response from a Claude Code session.

    Reads the session's JSONL file to get the last assistant message.
    Can optionally wait for a response if the session is still processing.

    Args:
        session_id: ID of the target session
        wait: If True, wait for Claude to finish if still processing
        timeout: Maximum seconds to wait

    Returns:
        Dict with status, response content, and metadata
    """
    from .session_state import wait_for_response as wait_for_resp

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    jsonl_path = session.get_jsonl_path()
    if not jsonl_path or not jsonl_path.exists():
        return error_response(
            "No JSONL session file found - Claude may not have started yet",
            hint=HINTS["no_jsonl_file"],
            session_id=session_id,
            status=session.status.value,
        )

    # Get current state
    state = session.get_conversation_state()
    if not state:
        return error_response(
            "Could not parse session state",
            hint="The JSONL file may be corrupted. Try closing and spawning a new session",
            session_id=session_id,
            status=session.status.value,
        )

    # If wait=True and session appears to be processing, wait for idle
    if wait and state.is_processing:
        response = await wait_for_resp(
            jsonl_path=jsonl_path,
            timeout=timeout,
            idle_threshold=2.0,
        )
        # Refresh state after waiting
        state = session.get_conversation_state()

    # Build response
    last_msg = state.last_assistant_message if state else None

    return {
        "session_id": session_id,
        "status": session.status.value,
        "is_processing": state.is_processing if state else False,
        "last_response": last_msg.content if last_msg else None,
        "message_id": last_msg.uuid if last_msg else None,
        "tool_uses": [t.get("name") for t in (last_msg.tool_uses if last_msg else [])],
        "message_count": state.message_count if state else 0,
    }


# Default page size for conversation history
CONVERSATION_PAGE_SIZE = 5

# Hint appended to messages sent to workers
WORKER_MESSAGE_HINT = "\n\n---\n(Note: Use the `bd_help` tool for guidance on using beads to track progress and add comments.)"

# Condensed beads help text for workers
BEADS_HELP_TEXT = """# Beads Quick Reference

Beads is a lightweight issue tracker. Use it to track progress and communicate with the coordinator.

## Essential Commands

```bash
bd list                              # List all issues
bd ready                             # Show unblocked work
bd show <issue-id>                   # Show issue details
bd update <id> --status in_progress  # Mark as in-progress
bd comment <id> "message"            # Add progress note (IMPORTANT!)
bd close <id>                        # Close when complete
```

## Status Values
- `open` - Not started
- `in_progress` - Currently working
- `closed` - Complete

## Priority Levels
- `P0` - Critical
- `P1` - High
- `P2` - Medium
- `P3` - Low

## Types
- `task` - Standard work item
- `bug` - Something broken
- `feature` - New functionality
- `epic` - Large multi-task effort
- `chore` - Maintenance work

## As a Worker

**IMPORTANT**: You should NOT close beads unless explicitly told to. Instead:

1. Mark your issue as in-progress when starting:
   ```bash
   bd update <issue-id> --status in_progress
   ```

2. Add comments to document your progress:
   ```bash
   bd comment <issue-id> "Completed the API endpoint, now working on tests"
   bd comment <issue-id> "Found edge case - handling null values in response"
   ```

3. When finished, add a final summary comment:
   ```bash
   bd comment <issue-id> "COMPLETE: Implemented feature X. Changes in src/foo.py and tests/test_foo.py. Ready for review."
   ```

4. The coordinator will review and close the bead.

## Creating New Issues (if needed)

```bash
bd create --title "Bug: X doesn't work" --type bug --priority P1 --description "Details..."
```

## Searching

```bash
bd search "keyword"          # Search by text
bd list --status open        # Filter by status
bd list --type bug           # Filter by type
bd blocked                   # Show blocked issues
```
"""


@mcp.tool()
async def bd_help() -> dict:
    """
    Get a quick reference guide for using Beads issue tracking.

    Returns condensed documentation on beads commands, workflow patterns,
    and best practices for worker sessions. Call this tool when you need
    guidance on tracking progress, adding comments, or managing issues.

    Returns:
        Dict with help text and key command examples
    """
    return {
        "help": BEADS_HELP_TEXT,
        "quick_commands": {
            "list_issues": "bd list",
            "show_ready": "bd ready",
            "show_issue": "bd show <issue-id>",
            "start_work": "bd update <id> --status in_progress",
            "add_comment": 'bd comment <id> "progress message"',
            "close_issue": "bd close <id>",
            "search": "bd search <query>",
        },
        "worker_tip": (
            "As a worker, add comments to track progress rather than closing issues. "
            "The coordinator will close issues after reviewing your work."
        ),
    }


@mcp.tool()
async def get_conversation_history(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    pages: int = 1,
    offset: int = 0,
) -> dict:
    """
    Get conversation history from a Claude Code session with reverse pagination.

    Returns messages from the session's JSONL file, paginated from the end
    (most recent first by default). Each message includes text content,
    tool use names/inputs, and thinking blocks.

    Pagination works from the end of the conversation:
    - pages=1, offset=0: Returns the most recent page (default)
    - pages=3, offset=0: Returns the last 3 pages in chronological order
    - pages=2, offset=1: Returns 2 pages, skipping the most recent page

    Page size is 5 messages (each user or assistant message counts as 1).

    Args:
        session_id: ID of the target session
        pages: Number of pages to return (default 1)
        offset: Number of pages to skip from the end (default 0 = most recent)

    Returns:
        Dict with:
            - messages: List of message dicts in chronological order
            - page_info: Pagination metadata (total_messages, total_pages, etc.)
            - session_id: The session ID
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Validate inputs
    if pages < 1:
        return error_response(
            "pages must be at least 1",
            hint="Use pages=1 to get the most recent page",
        )
    if offset < 0:
        return error_response(
            "offset must be non-negative",
            hint="Use offset=0 for most recent, offset=1 to skip most recent page, etc.",
        )

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    jsonl_path = session.get_jsonl_path()
    if not jsonl_path or not jsonl_path.exists():
        return error_response(
            "No JSONL session file found - Claude may not have started yet",
            hint=HINTS["no_jsonl_file"],
            session_id=session_id,
            status=session.status.value,
        )

    # Parse the session state
    state = session.get_conversation_state()
    if not state:
        return error_response(
            "Could not parse session state",
            hint="The JSONL file may be corrupted. Try closing and spawning a new session",
            session_id=session_id,
            status=session.status.value,
        )

    # Get all messages (user and assistant with content)
    all_messages = state.conversation
    total_messages = len(all_messages)
    total_pages = (total_messages + CONVERSATION_PAGE_SIZE - 1) // CONVERSATION_PAGE_SIZE

    if total_messages == 0:
        return {
            "session_id": session_id,
            "messages": [],
            "page_info": {
                "total_messages": 0,
                "total_pages": 0,
                "page_size": CONVERSATION_PAGE_SIZE,
                "pages_returned": 0,
                "offset": offset,
            },
        }

    # Calculate which messages to return using reverse pagination
    # offset=0 means start from the end, offset=1 means skip 1 page from end, etc.
    messages_to_skip_from_end = offset * CONVERSATION_PAGE_SIZE
    messages_to_take = pages * CONVERSATION_PAGE_SIZE

    # Calculate start and end indices
    # We're working backwards from the end
    end_index = total_messages - messages_to_skip_from_end
    start_index = max(0, end_index - messages_to_take)

    # Handle edge cases
    if end_index <= 0:
        return {
            "session_id": session_id,
            "messages": [],
            "page_info": {
                "total_messages": total_messages,
                "total_pages": total_pages,
                "page_size": CONVERSATION_PAGE_SIZE,
                "pages_returned": 0,
                "offset": offset,
                "note": f"Offset {offset} is beyond available messages",
            },
        }

    # Slice messages (already in chronological order)
    selected_messages = all_messages[start_index:end_index]

    # Convert to dicts
    message_dicts = [msg.to_dict() for msg in selected_messages]

    # Calculate actual pages returned
    pages_returned = (len(selected_messages) + CONVERSATION_PAGE_SIZE - 1) // CONVERSATION_PAGE_SIZE

    return {
        "session_id": session_id,
        "messages": message_dicts,
        "page_info": {
            "total_messages": total_messages,
            "total_pages": total_pages,
            "page_size": CONVERSATION_PAGE_SIZE,
            "pages_returned": pages_returned,
            "messages_returned": len(selected_messages),
            "offset": offset,
            "start_index": start_index,
            "end_index": end_index,
        },
    }


@mcp.tool()
async def get_session_status(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
) -> dict:
    """
    Get detailed status of a Claude Code session.

    Returns comprehensive information including conversation statistics
    and processing state. Use conversation_stats.last_assistant_preview
    to see what the worker last said.

    Args:
        session_id: ID of the target session

    Returns:
        Dict with detailed session status
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    result = session.to_dict()

    # Get conversation stats from JSONL
    # Use state.conversation (messages with content) for consistent counts
    state = session.get_conversation_state()
    if state:
        convo = state.conversation  # Only messages with text content
        user_msgs = [m for m in convo if m.role == "user"]
        assistant_msgs = [m for m in convo if m.role == "assistant"]

        result["conversation_stats"] = {
            "total_messages": len(convo),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "last_user_prompt": (
                user_msgs[-1].content[:200] + "..."
                if user_msgs and len(user_msgs[-1].content) > 200
                else (user_msgs[-1].content if user_msgs else None)
            ),
            "last_assistant_preview": (
                assistant_msgs[-1].content[:200] + "..."
                if assistant_msgs and len(assistant_msgs[-1].content) > 200
                else (assistant_msgs[-1].content if assistant_msgs else None)
            ),
        }
        result["is_processing"] = state.is_processing
    else:
        result["conversation_stats"] = None
        result["is_processing"] = None

    return result


@mcp.tool()
async def annotate_session(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    annotation: str,
) -> dict:
    """
    Add a coordinator annotation to a session.

    Coordinators use this to track what task each worker is assigned to.
    These annotations appear in list_sessions output.

    Args:
        session_id: The session to annotate
        annotation: Note about what this worker is working on

    Returns:
        Confirmation that the annotation was saved
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    session.controller_annotation = annotation
    session.update_activity()

    return {
        "success": True,
        "session_id": session_id,
        "annotation": annotation,
        "message": "Annotation saved",
    }


@mcp.tool()
async def discover_sessions(
    ctx: Context[ServerSession, AppContext],
) -> dict:
    """
    Discover existing Claude Code sessions running in iTerm2.

    Scans all iTerm2 windows, tabs, and panes to find sessions that appear
    to be running Claude Code. Attempts to match each session to its JSONL
    file in ~/.claude/projects/ based on the project path visible on screen.

    Returns:
        Dict with:
            - sessions: List of discovered sessions, each containing:
                - iterm_session_id: iTerm2's internal session ID
                - project_path: Detected project path (if found)
                - claude_session_id: Matched JSONL session ID (if found)
                - model: Detected model (Opus/Sonnet/Haiku if visible)
                - last_assistant_preview: Preview of last assistant message (if JSONL found)
                - already_managed: True if this session is already in our registry
            - count: Total number of Claude sessions found
            - unmanaged_count: Number not yet imported into registry
    """
    from .session_state import (
        CLAUDE_PROJECTS_DIR,
        find_active_session,
        get_project_dir,
        list_sessions,
        parse_session,
        unslugify_path,
    )

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Ensure we have a fresh connection (websocket can go stale)
    _, app = await ensure_connection(app_ctx)

    discovered = []

    # Get all managed iTerm session IDs so we can flag already-managed ones
    managed_iterm_ids = {
        s.iterm_session.session_id for s in registry.list_all()
    }

    # Scan all iTerm2 sessions
    for window in app.terminal_windows:
        for tab in window.tabs:
            for iterm_session in tab.sessions:
                try:
                    screen_text = await read_screen_text(iterm_session)

                    # Detect if this is a Claude Code session by looking for indicators:
                    # - Model name (Opus, Sonnet, Haiku)
                    # - Prompt character (>)
                    # - Common Claude Code UI elements
                    is_claude = False
                    detected_model = None

                    for model in ["Opus", "Sonnet", "Haiku"]:
                        if model in screen_text:
                            is_claude = True
                            detected_model = model
                            break

                    # Also check for Claude-specific patterns
                    if not is_claude:
                        # Look for status line patterns: "ctx:", "tokens", "api:✓"
                        if "ctx:" in screen_text or "tokens" in screen_text:
                            is_claude = True

                    if not is_claude:
                        continue

                    # Try to extract project path from screen
                    # Look for "git:(" pattern which shows git branch, indicating project dir
                    # Or extract from visible path patterns
                    project_path = None
                    claude_session_id = None

                    # Parse screen lines for project info
                    lines = [l.strip() for l in screen_text.split("\n") if l.strip()]

                    # Look for git branch indicator which often shows project name
                    for line in lines:
                        # Pattern: "project-name git:(branch)" in status line
                        if "git:(" in line:
                            # Extract the part before "git:("
                            parts = line.split("git:(")[0].strip().split()
                            if parts:
                                project_name = parts[-1]
                                # Try to find this project in Claude's projects dir
                                for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
                                    if proj_dir.is_dir() and project_name in proj_dir.name:
                                        # Use unslugify_path to handle hyphens in names
                                        # correctly (e.g., claude-iterm-controller)
                                        reconstructed = unslugify_path(proj_dir.name)
                                        if reconstructed:
                                            project_path = reconstructed
                                            break
                            break

                    # If we found a project path, try to find the active JSONL session
                    if project_path:
                        # Find most recently active session for this project
                        claude_session_id = find_active_session(
                            project_path, max_age_seconds=3600  # Within last hour
                        )

                    # Get last assistant message preview from JSONL if available
                    last_assistant_preview = None
                    if project_path and claude_session_id:
                        try:
                            jsonl_path = get_project_dir(project_path) / f"{claude_session_id}.jsonl"
                            if jsonl_path.exists():
                                state = parse_session(jsonl_path)
                                if state.last_assistant_message:
                                    content = state.last_assistant_message.content
                                    last_assistant_preview = (
                                        content[:200] + "..."
                                        if len(content) > 200
                                        else content
                                    )
                        except Exception as e:
                            logger.debug(f"Could not get conversation preview: {e}")

                    discovered.append({
                        "iterm_session_id": iterm_session.session_id,
                        "project_path": project_path,
                        "claude_session_id": claude_session_id,
                        "model": detected_model,
                        "last_assistant_preview": last_assistant_preview,
                        "already_managed": iterm_session.session_id in managed_iterm_ids,
                    })

                except Exception as e:
                    logger.warning(f"Error scanning session {iterm_session.session_id}: {e}")
                    continue

    unmanaged = [s for s in discovered if not s["already_managed"]]

    return {
        "sessions": discovered,
        "count": len(discovered),
        "unmanaged_count": len(unmanaged),
    }


@mcp.tool()
async def import_session(
    ctx: Context[ServerSession, AppContext],
    iterm_session_id: str,
    project_path: str | None = None,
    session_name: str | None = None,
) -> dict:
    """
    Import an existing iTerm2 Claude Code session into the MCP registry.

    Takes an iTerm2 session ID (from discover_sessions) and registers it
    for management. This allows you to send messages and get responses
    from sessions that were started outside this MCP server.

    Args:
        iterm_session_id: The iTerm2 session ID (from discover_sessions)
        project_path: Optional explicit project path. If not provided,
            will attempt to detect from screen content.
        session_name: Optional friendly name for the session

    Returns:
        Dict with imported session info, or error if session not found
    """
    from .session_state import CLAUDE_PROJECTS_DIR, find_active_session

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Ensure we have a fresh connection (websocket can go stale)
    _, app = await ensure_connection(app_ctx)

    # Check if already managed
    for managed in registry.list_all():
        if managed.iterm_session.session_id == iterm_session_id:
            return {
                "error": f"Session already managed as '{managed.session_id}'",
                "existing_session": managed.to_dict(),
            }

    # Find the iTerm2 session by ID
    target_session = None
    for window in app.terminal_windows:
        for tab in window.tabs:
            for iterm_session in tab.sessions:
                if iterm_session.session_id == iterm_session_id:
                    target_session = iterm_session
                    break
            if target_session:
                break
        if target_session:
            break

    if not target_session:
        return error_response(
            f"iTerm2 session not found: {iterm_session_id}",
            hint="Run discover_sessions to scan for active Claude sessions in iTerm2",
        )

    # If project_path not provided, try to detect it
    if not project_path:
        try:
            screen_text = await read_screen_text(target_session)
            lines = screen_text.split("\n")

            # Try to find project from git branch indicator
            for line in lines:
                if "git:(" in line:
                    parts = line.split("git:(")[0].strip().split()
                    if parts:
                        project_name = parts[-1]
                        # Search Claude projects directory
                        for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
                            if proj_dir.is_dir() and project_name in proj_dir.name:
                                project_path = proj_dir.name.replace("-", "/")
                                if project_path.startswith("/"):
                                    break
                    break
        except Exception as e:
            logger.warning(f"Could not detect project path: {e}")

    if not project_path:
        return error_response(
            "Could not detect project path from terminal",
            hint=HINTS["project_path_detection_failed"],
            iterm_session_id=iterm_session_id,
        )

    # Validate project path exists
    if not os.path.isdir(project_path):
        return error_response(
            f"Project path does not exist: {project_path}",
            hint=HINTS["project_path_missing"],
        )

    # Register the session
    managed = registry.add(
        iterm_session=target_session,
        project_path=project_path,
        name=session_name,
    )

    # Send marker message for JSONL correlation
    from .session_state import generate_marker_message

    marker_message = generate_marker_message(managed.session_id)
    await send_prompt(target_session, marker_message, submit=True)

    # Wait for marker to be logged, then discover by marker
    await asyncio.sleep(2)
    if not managed.discover_claude_session_by_marker():
        # Fallback to old discovery if marker not found
        logger.warning(
            f"Marker-based discovery failed for {managed.session_id}, "
            "falling back to timestamp-based discovery"
        )
        managed.discover_claude_session()

    # Update status to ready (it's already running)
    registry.update_status(managed.session_id, SessionStatus.READY)

    return {
        "success": True,
        "message": f"Session imported as '{managed.session_id}'",
        "session": managed.to_dict(),
    }


@mcp.tool()
async def close_session(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    force: bool = False,
) -> dict:
    """
    Close a managed Claude Code session.

    Gracefully terminates the Claude session and optionally closes
    the iTerm2 window/pane.

    Args:
        session_id: ID of the session to close
        force: If True, force close even if session is busy

    Returns:
        Dict with success status
    """
    from .iterm_utils import send_key, close_pane

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    # Check if busy
    if session.status == SessionStatus.BUSY and not force:
        return error_response(
            "Session is busy",
            hint=HINTS["session_busy"],
            session_id=session_id,
            status=session.status.value,
        )

    try:
        # Send Ctrl+C to interrupt any running operation
        await send_key(session.iterm_session, "ctrl-c")
        await asyncio.sleep(0.5)

        # Send /exit to quit Claude
        await send_prompt(session.iterm_session, "/exit", submit=True)
        await asyncio.sleep(1.0)

        # Clean up worktree if exists
        worktree_cleaned = False
        if session.worktree_path:
            try:
                remove_worktree(
                    repo_path=Path(session.project_path),
                    worktree_name=session.worktree_path.name,
                )
                worktree_cleaned = True
            except WorktreeError as e:
                # Log but don't fail the close
                logger.warning(f"Failed to clean up worktree for {session_id}: {e}")

        # Close the iTerm2 pane/window
        await close_pane(session.iterm_session, force=force)

        # Update status
        registry.update_status(session_id, SessionStatus.CLOSED)

        # Remove from registry
        registry.remove(session_id)

        return {
            "success": True,
            "session_id": session_id,
            "message": "Session closed, pane terminated, and removed from registry",
            "worktree_cleaned": worktree_cleaned,
        }

    except Exception as e:
        logger.error(f"Failed to close session: {e}")
        # Still try to remove from registry
        registry.update_status(session_id, SessionStatus.CLOSED)
        registry.remove(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "warning": f"Session removed but cleanup may be incomplete: {e}",
            "worktree_cleaned": False,
        }


# =============================================================================
# Task Completion Detection Tools
# =============================================================================


@mcp.tool()
async def get_task_status(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
) -> dict:
    """
    Get the completion status of a delegated task.

    Uses Stop hook detection to determine if a task is complete. When Claude
    finishes responding, the Stop hook fires and logs a marker to the JSONL.
    This is authoritative — either done or not done.

    Args:
        session_id: ID of the session to check

    Returns:
        Dict with:
            - status: "in_progress", "completed", or "unknown"
            - detection_method: "stop_hook"
            - details: Additional information about the detection
            - has_active_task: Whether a task is currently being tracked
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    # Check if there's an active task
    if not session.current_task:
        return error_response(
            "No active task being tracked",
            hint=HINTS["no_active_task"],
            session_id=session_id,
            has_active_task=False,
            status=TaskStatus.UNKNOWN.value,
        )

    # Get JSONL path
    jsonl_path = session.get_jsonl_path()
    if not jsonl_path:
        return error_response(
            "No JSONL session file found",
            hint=HINTS["no_jsonl_file"],
            session_id=session_id,
            status=TaskStatus.UNKNOWN.value,
        )

    # Run detection
    result = detect_completion(jsonl_path, session_id)

    # If completed, archive the task
    if result.status == TaskStatus.COMPLETED:
        session.complete_task()
        registry.update_status(session_id, SessionStatus.READY)

    return {
        "session_id": session_id,
        "has_active_task": session.current_task is not None,
        "task_id": session.current_task.task_id if session.current_task else None,
        "task_description": (
            session.current_task.description[:100] + "..."
            if session.current_task and len(session.current_task.description) > 100
            else (session.current_task.description if session.current_task else None)
        ),
        **result.to_dict(),
    }


@mcp.tool()
async def wait_for_completion(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    timeout: float = 300.0,
    poll_interval: float = 2.0,
) -> dict:
    """
    Wait for a delegated task to complete.

    Polls until the Stop hook fires or timeout is reached. When Claude finishes
    responding, the Stop hook fires immediately — no guessing, no heuristics.

    Args:
        session_id: ID of the session to wait on
        timeout: Maximum seconds to wait (default 5 minutes)
        poll_interval: Seconds between checks (default 2)

    Returns:
        Dict with:
            - status: "completed" or "in_progress" (if timeout)
            - detection_method: "stop_hook"
            - details: Additional information
            - waited_seconds: How long we actually waited
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    # Check if there's an active task
    if not session.current_task:
        return error_response(
            "No active task being tracked",
            hint=HINTS["no_active_task"],
            session_id=session_id,
            has_active_task=False,
            status=TaskStatus.UNKNOWN.value,
        )

    # Get JSONL path
    jsonl_path = session.get_jsonl_path()
    if not jsonl_path:
        return error_response(
            "No JSONL session file found",
            hint=HINTS["no_jsonl_file"],
            session_id=session_id,
        )

    # Wait for completion
    result = await wait_for_completion_impl(
        jsonl_path=jsonl_path,
        session_id=session_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    # If completed, archive the task
    if result.status == TaskStatus.COMPLETED:
        session.complete_task()
        registry.update_status(session_id, SessionStatus.READY)

    return {
        "session_id": session_id,
        "task_id": session.current_task.task_id if session.current_task else None,
        **result.to_dict(),
    }


@mcp.tool()
async def cancel_task(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
) -> dict:
    """
    Cancel tracking of the current task without waiting for completion.

    This does not stop the Claude session from working - it only stops
    tracking the task for completion detection. Useful if you want to
    abandon waiting and start a new task.

    Args:
        session_id: ID of the session

    Returns:
        Dict with the cancelled task info
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    if not session.current_task:
        return {
            "session_id": session_id,
            "message": "No active task to cancel",
        }

    # Archive the task
    cancelled = session.complete_task()

    return {
        "session_id": session_id,
        "cancelled": True,
        "task_id": cancelled.task_id if cancelled else None,
        "task_description": (
            cancelled.description[:100] + "..."
            if cancelled and len(cancelled.description) > 100
            else (cancelled.description if cancelled else None)
        ),
    }


# =============================================================================
# MCP Resources
# =============================================================================


@mcp.resource("sessions://list")
async def resource_sessions(ctx: Context[ServerSession, AppContext]) -> list[dict]:
    """
    List all managed Claude Code sessions.

    Returns a list of session summaries including ID, name, project path,
    status, and conversation stats if available. This is a read-only
    resource alternative to the list_sessions tool.
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    sessions = registry.list_all()
    results = []

    for session in sessions:
        info = session.to_dict()
        # Add conversation stats if JSONL is available
        state = session.get_conversation_state()
        if state:
            info["message_count"] = state.message_count
            info["is_processing"] = state.is_processing
        results.append(info)

    return results


@mcp.resource("sessions://{session_id}/status")
async def resource_session_status(
    session_id: str, ctx: Context[ServerSession, AppContext]
) -> dict:
    """
    Get detailed status of a specific Claude Code session.

    Returns comprehensive information including session metadata,
    conversation statistics, and processing state. Use the /screen
    resource to get terminal screen content.

    Args:
        session_id: ID of the target session
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    result = session.to_dict()

    # Get conversation stats from JSONL
    # Use state.conversation (messages with content) for consistent counts
    state = session.get_conversation_state()
    if state:
        convo = state.conversation  # Only messages with text content
        user_msgs = [m for m in convo if m.role == "user"]
        assistant_msgs = [m for m in convo if m.role == "assistant"]

        result["conversation_stats"] = {
            "total_messages": len(convo),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "last_user_prompt": (
                user_msgs[-1].content[:200] + "..."
                if user_msgs and len(user_msgs[-1].content) > 200
                else (user_msgs[-1].content if user_msgs else None)
            ),
            "last_assistant_preview": (
                assistant_msgs[-1].content[:200] + "..."
                if assistant_msgs and len(assistant_msgs[-1].content) > 200
                else (assistant_msgs[-1].content if assistant_msgs else None)
            ),
        }
        result["is_processing"] = state.is_processing
        result["message_count"] = state.message_count
    else:
        result["conversation_stats"] = None
        result["is_processing"] = None
        result["message_count"] = 0

    return result


@mcp.resource("sessions://{session_id}/screen")
async def resource_session_screen(
    session_id: str, ctx: Context[ServerSession, AppContext]
) -> dict:
    """
    Get the current terminal screen content for a session.

    Returns the visible text in the iTerm2 pane for the specified session.
    Useful for checking what Claude is currently displaying or doing.

    Args:
        session_id: ID of the target session
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    session = registry.get(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )

    try:
        screen_text = await read_screen_text(session.iterm_session)
        # Get non-empty lines
        lines = [line for line in screen_text.split("\n") if line.strip()]

        return {
            "session_id": session_id,
            "screen_content": screen_text,
            "screen_preview": "\n".join(lines[-15:]) if lines else "",
            "line_count": len(lines),
            "is_responsive": True,
        }
    except Exception as e:
        return error_response(
            f"Could not read screen: {e}",
            hint=HINTS["iterm_connection"],
            session_id=session_id,
            is_responsive=False,
        )


# =============================================================================
# Server Entry Point
# =============================================================================


def run_server():
    """Run the MCP server with stdio transport."""
    logger.info("Starting Claude Team MCP Server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
