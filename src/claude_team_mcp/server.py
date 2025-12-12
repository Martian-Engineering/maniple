"""
Claude Team MCP Server

FastMCP-based server for managing multiple Claude Code sessions via iTerm2.
Allows a "manager" Claude Code session to spawn and coordinate multiple
"worker" Claude Code sessions.
"""

import asyncio
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .iterm_utils import (
    LAYOUT_PANE_NAMES,
    create_multi_claude_layout,
    create_window,
    read_screen_text,
    send_prompt,
    split_pane,
    start_claude_in_session,
)
from .registry import SessionRegistry, SessionStatus, TaskInfo
from .task_completion import (
    TaskContext,
    TaskCompletionInfo,
    TaskStatus,
    detect_task_completion,
    wait_for_task_completion,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("claude-team-mcp")


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


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Manage iTerm2 connection lifecycle.

    Connects to iTerm2 on startup and maintains the connection
    for the duration of the server's lifetime.
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
async def spawn_session(
    ctx: Context[ServerSession, AppContext],
    project_path: str,
    session_name: str | None = None,
    layout: str = "new_window",
    skip_permissions: bool = False,
    split_from_session: str | None = None,
) -> dict:
    """
    Spawn a new Claude Code session in iTerm2.

    Creates a new iTerm2 window or pane, starts Claude Code in it,
    and registers it for management.

    Args:
        project_path: Directory where Claude Code should run
        session_name: Optional friendly name for the session
        layout: How to create the session - "new_window", "split_vertical", or "split_horizontal"
        skip_permissions: If True, start Claude with --dangerously-skip-permissions flag
        split_from_session: For split layouts, ID of existing managed session to split from.
            If not provided, splits the currently active iTerm window.

    Returns:
        Dict with session_id, status, and project_path
    """
    app_ctx = ctx.request_context.lifespan_context
    connection = app_ctx.iterm_connection
    app = app_ctx.iterm_app
    registry = app_ctx.registry

    # Validate project path
    resolved_path = os.path.abspath(os.path.expanduser(project_path))
    if not os.path.isdir(resolved_path):
        return {"error": f"Project path does not exist: {resolved_path}"}

    try:
        # Create iTerm2 session based on layout
        if layout == "new_window":
            # Create a new window
            window = await create_window(connection)
            iterm_session = window.current_tab.current_session
        elif layout in ("split_vertical", "split_horizontal"):
            vertical = layout == "split_vertical"

            # Determine which session to split from
            if split_from_session:
                # Split from a specific managed session
                source_session = registry.get(split_from_session)
                if not source_session:
                    return {"error": f"split_from_session not found: {split_from_session}"}
                iterm_session = await split_pane(source_session.iterm_session, vertical=vertical)
            else:
                # Split the current window's active session (original behavior)
                current_window = app.current_terminal_window
                if current_window is None:
                    # No window exists, create one
                    window = await create_window(connection)
                    iterm_session = window.current_tab.current_session
                else:
                    current_session = current_window.current_tab.current_session
                    iterm_session = await split_pane(current_session, vertical=vertical)
        else:
            return {"error": f"Invalid layout: {layout}. Use: new_window, split_vertical, split_horizontal"}

        # Register the session before starting Claude (so we track it even if startup fails)
        managed = registry.add(
            iterm_session=iterm_session,
            project_path=resolved_path,
            name=session_name,
        )

        # Check if this is a git worktree and set BEADS_DIR if needed
        env = None
        beads_dir = get_worktree_beads_dir(resolved_path)
        if beads_dir:
            env = {"BEADS_DIR": beads_dir}

        # Start Claude Code in the session
        await start_claude_in_session(
            session=iterm_session,
            project_path=resolved_path,
            wait_seconds=4.0,
            dangerously_skip_permissions=skip_permissions,
            env=env,
        )

        # Try to discover the Claude session ID from JSONL
        await asyncio.sleep(1)  # Give Claude a moment to create the session file
        managed.discover_claude_session()

        # Update status to ready
        registry.update_status(managed.session_id, SessionStatus.READY)

        return managed.to_dict()

    except Exception as e:
        logger.error(f"Failed to spawn session: {e}")
        return {"error": str(e)}


@mcp.tool()
async def spawn_team(
    ctx: Context[ServerSession, AppContext],
    projects: dict[str, str],
    layout: str = "quad",
    skip_permissions: bool = False,
) -> dict:
    """
    Spawn multiple Claude Code sessions in a multi-pane layout.

    Creates a new iTerm2 window with the specified pane layout and starts
    Claude Code in each pane. All sessions are registered for management.

    Args:
        projects: Dict mapping pane names to project paths. Keys must match
            the layout's pane names:
            - "vertical": ["left", "right"]
            - "horizontal": ["top", "bottom"]
            - "quad": ["top_left", "top_right", "bottom_left", "bottom_right"]
            - "triple_vertical": ["left", "middle", "right"]
        layout: Layout type - "vertical", "horizontal", "quad", or "triple_vertical"
        skip_permissions: If True, start Claude with --dangerously-skip-permissions

    Returns:
        Dict with:
            - sessions: Dict mapping pane names to session info (id, status, project_path)
            - layout: The layout used
            - count: Number of sessions created

    Example:
        spawn_team(
            projects={
                "top_left": "/path/to/frontend",
                "top_right": "/path/to/backend",
                "bottom_left": "/path/to/api",
                "bottom_right": "/path/to/tests"
            },
            layout="quad"
        )
    """
    app_ctx = ctx.request_context.lifespan_context
    connection = app_ctx.iterm_connection
    registry = app_ctx.registry

    # Validate layout
    if layout not in LAYOUT_PANE_NAMES:
        return {
            "error": f"Invalid layout: {layout}. "
            f"Valid layouts: {list(LAYOUT_PANE_NAMES.keys())}"
        }

    # Validate pane names
    expected_panes = set(LAYOUT_PANE_NAMES[layout])
    provided_panes = set(projects.keys())
    if not provided_panes.issubset(expected_panes):
        invalid = provided_panes - expected_panes
        return {
            "error": f"Invalid pane names for layout '{layout}': {list(invalid)}. "
            f"Valid names: {list(expected_panes)}"
        }

    # Validate all project paths exist and detect worktrees
    resolved_projects = {}
    project_envs: dict[str, dict[str, str]] = {}
    for pane_name, project_path in projects.items():
        resolved = os.path.abspath(os.path.expanduser(project_path))
        if not os.path.isdir(resolved):
            return {"error": f"Project path does not exist for '{pane_name}': {resolved}"}
        resolved_projects[pane_name] = resolved

        # Check for worktree and set BEADS_DIR if needed
        beads_dir = get_worktree_beads_dir(resolved)
        if beads_dir:
            project_envs[pane_name] = {"BEADS_DIR": beads_dir}

    try:
        # Create the multi-pane layout and start Claude in each pane
        pane_sessions = await create_multi_claude_layout(
            connection=connection,
            projects=resolved_projects,
            layout=layout,
            skip_permissions=skip_permissions,
            project_envs=project_envs if project_envs else None,
        )

        # Register all sessions first (this is quick, no I/O)
        managed_sessions = {}
        for pane_name, iterm_session in pane_sessions.items():
            managed = registry.add(
                iterm_session=iterm_session,
                project_path=resolved_projects[pane_name],
                name=f"{layout}_{pane_name}",  # e.g., "quad_top_left"
            )
            managed_sessions[pane_name] = managed

        # Single batch sleep to give Claude time to create session files.
        # This replaces sequential 1s sleeps per session.
        await asyncio.sleep(1)

        # Discover Claude sessions and update status for all
        result_sessions = {}
        for pane_name, managed in managed_sessions.items():
            managed.discover_claude_session()
            registry.update_status(managed.session_id, SessionStatus.READY)
            result_sessions[pane_name] = managed.to_dict()

        return {
            "sessions": result_sessions,
            "layout": layout,
            "count": len(result_sessions),
        }

    except ValueError as e:
        # Layout or pane name validation errors from the primitive
        logger.error(f"Validation error in spawn_team: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Failed to spawn team: {e}")
        return {"error": str(e)}


@mcp.tool()
async def list_sessions(
    ctx: Context[ServerSession, AppContext],
    status_filter: str | None = None,
) -> list[dict]:
    """
    List all managed Claude Code sessions.

    Returns information about each session including its ID, name,
    project path, and current status.

    Args:
        status_filter: Optional filter by status - "ready", "busy", "spawning", "closed"

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
            return [{"error": f"Invalid status filter: {status_filter}"}]
    else:
        sessions = registry.list_all()

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
        session_id: ID of the target session (from spawn_session or list_sessions)
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
        return {"error": f"Session not found: {session_id}"}

    # Check session is ready
    if session.status == SessionStatus.CLOSED:
        return {"error": f"Session is closed: {session_id}"}

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

        # Send the message to the terminal
        await send_prompt(session.iterm_session, message, submit=True)

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
                    result["response_preview"] = (
                        response.content[:500] + "..."
                        if len(response.content) > 500
                        else response.content
                    )
                else:
                    result["response"] = None
                    result["timeout"] = True

        # Update status back to ready
        registry.update_status(session_id, SessionStatus.READY)

        return result

    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        registry.update_status(session_id, SessionStatus.READY)
        return {"error": str(e), "session_id": session_id}


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
        return {"error": "No session_ids provided"}

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
        results[sid] = {"error": f"Session not found: {sid}", "success": False}

    for sid in closed_sessions:
        results[sid] = {"error": f"Session is closed: {sid}", "success": False}

    if not valid_sessions:
        return {
            "results": results,
            "success_count": 0,
            "failure_count": len(results),
            "total": len(session_ids),
            "error": "No valid sessions to send to",
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

            # Send the message to the terminal
            await send_prompt(session.iterm_session, message, submit=True)

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
                        result["response_preview"] = (
                            response.content[:500] + "..."
                            if len(response.content) > 500
                            else response.content
                        )
                    else:
                        result["response"] = None
                        result["timeout"] = True

            # Update status back to ready
            registry.update_status(sid, SessionStatus.READY)

            return (sid, result)

        except Exception as e:
            logger.error(f"Failed to send message to {sid}: {e}")
            registry.update_status(sid, SessionStatus.READY)
            return (sid, {"error": str(e), "session_id": sid, "success": False})

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
        return {"error": f"Session not found: {session_id}"}

    jsonl_path = session.get_jsonl_path()
    if not jsonl_path or not jsonl_path.exists():
        return {
            "session_id": session_id,
            "status": session.status.value,
            "error": "No JSONL session file found - Claude may not have started yet",
        }

    # Get current state
    state = session.get_conversation_state()
    if not state:
        return {
            "session_id": session_id,
            "status": session.status.value,
            "error": "Could not parse session state",
        }

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
        "last_response_preview": (
            last_msg.content[:500] + "..."
            if last_msg and len(last_msg.content) > 500
            else (last_msg.content if last_msg else None)
        ),
        "message_id": last_msg.uuid if last_msg else None,
        "tool_uses": [t.get("name") for t in (last_msg.tool_uses if last_msg else [])],
        "message_count": state.message_count if state else 0,
    }


@mcp.tool()
async def get_session_status(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
) -> dict:
    """
    Get detailed status of a Claude Code session.

    Returns comprehensive information including terminal screen content,
    conversation statistics, and processing state.

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
        return {"error": f"Session not found: {session_id}"}

    result = session.to_dict()

    # Try to read screen content
    try:
        screen_text = await read_screen_text(session.iterm_session)
        # Get last few non-empty lines as preview
        lines = [l for l in screen_text.split("\n") if l.strip()]
        result["screen_preview"] = "\n".join(lines[-10:]) if lines else ""
        result["is_responsive"] = True
    except Exception as e:
        result["screen_preview"] = None
        result["is_responsive"] = False
        result["screen_error"] = str(e)

    # Get conversation stats from JSONL
    state = session.get_conversation_state()
    if state:
        user_msgs = [m for m in state.messages if m.role == "user"]
        assistant_msgs = [m for m in state.messages if m.role == "assistant"]

        result["conversation_stats"] = {
            "total_messages": len(state.messages),
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
                - screen_preview: Last few lines of screen content
                - already_managed: True if this session is already in our registry
            - count: Total number of Claude sessions found
            - unmanaged_count: Number not yet imported into registry
    """
    from .session_state import (
        CLAUDE_PROJECTS_DIR,
        find_active_session,
        list_sessions,
        unslugify_path,
    )

    app_ctx = ctx.request_context.lifespan_context
    app = app_ctx.iterm_app
    registry = app_ctx.registry

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

                    # Get last few lines as preview
                    preview_lines = [l for l in lines if l][-5:]
                    screen_preview = "\n".join(preview_lines)

                    discovered.append({
                        "iterm_session_id": iterm_session.session_id,
                        "project_path": project_path,
                        "claude_session_id": claude_session_id,
                        "model": detected_model,
                        "screen_preview": screen_preview,
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
    app = app_ctx.iterm_app
    registry = app_ctx.registry

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
        return {"error": f"iTerm2 session not found: {iterm_session_id}"}

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
        return {
            "error": "Could not detect project path. Please provide project_path explicitly.",
            "iterm_session_id": iterm_session_id,
        }

    # Validate project path exists
    if not os.path.isdir(project_path):
        return {"error": f"Project path does not exist: {project_path}"}

    # Register the session
    managed = registry.add(
        iterm_session=target_session,
        project_path=project_path,
        name=session_name,
    )

    # Try to discover Claude session ID from JSONL
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
        return {"error": f"Session not found: {session_id}"}

    # Check if busy
    if session.status == SessionStatus.BUSY and not force:
        return {
            "error": f"Session is busy. Use force=True to close anyway.",
            "session_id": session_id,
            "status": session.status.value,
        }

    try:
        # Send Ctrl+C to interrupt any running operation
        await send_key(session.iterm_session, "ctrl-c")
        await asyncio.sleep(0.5)

        # Send /exit to quit Claude
        await send_prompt(session.iterm_session, "/exit", submit=True)
        await asyncio.sleep(1.0)

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
        }


# =============================================================================
# Task Completion Detection Tools
# =============================================================================


@mcp.tool()
async def get_task_status(
    ctx: Context[ServerSession, AppContext],
    session_id: str,
    check_git: bool = True,
    check_beads: bool = True,
    check_screen: bool = True,
) -> dict:
    """
    Get the completion status of a delegated task.

    Uses multiple detection methods to determine if a task is complete:
    - Convention markers: Looks for TASK_COMPLETE, TASK_FAILED, etc. in conversation
    - Git commits: Checks for new commits since task started
    - Beads issues: Checks if linked beads issue was closed
    - Screen parsing: Looks for completion patterns in terminal output
    - Idle detection: Checks if session has been idle (suggesting completion)

    Args:
        session_id: ID of the session to check
        check_git: Whether to check for git commits
        check_beads: Whether to check beads issue status
        check_screen: Whether to parse screen content

    Returns:
        Dict with:
            - status: "pending", "in_progress", "completed", "failed", or "unknown"
            - confidence: 0.0 to 1.0 confidence in the detection
            - detection_method: Which method detected the status
            - details: Additional information about the detection
            - has_active_task: Whether a task is currently being tracked
    """
    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return {"error": f"Session not found: {session_id}"}

    # Check if there's an active task
    if not session.current_task:
        return {
            "session_id": session_id,
            "has_active_task": False,
            "status": TaskStatus.UNKNOWN.value,
            "message": "No active task being tracked. Use send_message with track_task=True.",
        }

    # Build task context
    task_ctx = TaskContext(
        session_id=session_id,
        project_path=session.project_path,
        started_at=session.current_task.started_at,
        baseline_message_uuid=session.current_task.baseline_message_uuid,
        beads_issue_id=session.current_task.beads_issue_id,
        task_description=session.current_task.description,
    )

    # Get session state
    session_state = session.get_conversation_state()

    # Run detection
    result = await detect_task_completion(
        task_ctx=task_ctx,
        session_state=session_state,
        iterm_session=session.iterm_session,
        read_screen_func=read_screen_text,
        check_git=check_git,
        check_beads=check_beads,
        check_screen=check_screen,
    )

    # If completed/failed with high confidence, archive the task
    if result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        if result.confidence >= 0.7:
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
    idle_threshold: float = 30.0,
    check_git: bool = True,
    check_beads: bool = True,
) -> dict:
    """
    Wait for a delegated task to complete.

    Polls the session state and other signals until completion is detected
    or timeout is reached. This is useful for synchronous workflows where
    you need to wait for a worker to finish.

    Detection is based on:
    - Convention markers (TASK_COMPLETE, etc.) in conversation
    - Git commits in the project
    - Beads issue status changes
    - Screen content patterns
    - Session idle time

    Args:
        session_id: ID of the session to wait on
        timeout: Maximum seconds to wait (default 5 minutes)
        poll_interval: Seconds between checks (default 2)
        idle_threshold: Seconds of inactivity to consider "complete" (default 30)
        check_git: Whether to check for git commits
        check_beads: Whether to check beads issue status

    Returns:
        Dict with:
            - status: Final task status
            - confidence: Confidence in the detection
            - detection_method: Which method detected completion
            - details: Additional information
            - waited_seconds: How long we actually waited
    """
    import time

    app_ctx = ctx.request_context.lifespan_context
    registry = app_ctx.registry

    # Look up session
    session = registry.get(session_id)
    if not session:
        return {"error": f"Session not found: {session_id}"}

    # Check if there's an active task
    if not session.current_task:
        return {
            "session_id": session_id,
            "has_active_task": False,
            "status": TaskStatus.UNKNOWN.value,
            "message": "No active task being tracked. Use send_message with track_task=True first.",
        }

    # Get JSONL path
    jsonl_path = session.get_jsonl_path()
    if not jsonl_path:
        return {
            "session_id": session_id,
            "error": "No JSONL session file found - cannot track conversation state",
        }

    # Build task context
    task_ctx = TaskContext(
        session_id=session_id,
        project_path=session.project_path,
        started_at=session.current_task.started_at,
        baseline_message_uuid=session.current_task.baseline_message_uuid,
        beads_issue_id=session.current_task.beads_issue_id,
        task_description=session.current_task.description,
    )

    start_time = time.time()

    # Wait for completion
    result = await wait_for_task_completion(
        task_ctx=task_ctx,
        jsonl_path=jsonl_path,
        timeout=timeout,
        poll_interval=poll_interval,
        idle_threshold=idle_threshold,
        iterm_session=session.iterm_session,
        read_screen_func=read_screen_text,
    )

    elapsed = time.time() - start_time

    # If completed/failed with good confidence, archive the task
    if result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        if result.confidence >= 0.7:
            completed_task = session.complete_task()
            registry.update_status(session_id, SessionStatus.READY)

    return {
        "session_id": session_id,
        "task_id": session.current_task.task_id if session.current_task else None,
        "waited_seconds": round(elapsed, 1),
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
        return {"error": f"Session not found: {session_id}"}

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
        return {"error": f"Session not found: {session_id}"}

    result = session.to_dict()

    # Get conversation stats from JSONL
    state = session.get_conversation_state()
    if state:
        user_msgs = [m for m in state.messages if m.role == "user"]
        assistant_msgs = [m for m in state.messages if m.role == "assistant"]

        result["conversation_stats"] = {
            "total_messages": len(state.messages),
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
        return {"error": f"Session not found: {session_id}"}

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
        return {
            "session_id": session_id,
            "error": f"Could not read screen: {e}",
            "is_responsive": False,
        }


# =============================================================================
# Server Entry Point
# =============================================================================


def run_server():
    """Run the MCP server with stdio transport."""
    logger.info("Starting Claude Team MCP Server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
