"""
Spawn workers tool.

Provides spawn_workers for creating new Claude Code worker sessions.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Required, TypedDict

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..cli_backends import get_cli_backend
from ..config import ConfigError, default_config, load_config
from ..colors import generate_tab_color
from ..formatting import format_badge_text, format_session_title
from ..names import pick_names_for_count
from ..profile import apply_appearance_colors
from ..registry import SessionStatus
from ..terminal_backends import ItermBackend, MAX_PANES_PER_TAB
from ..utils import HINTS, error_response, get_worktree_tracker_dir
from ..worker_prompt import generate_worker_prompt, get_coordinator_guidance
from ..worktree import WorktreeError, create_local_worktree

logger = logging.getLogger("claude-team-mcp")


class WorktreeConfig(TypedDict, total=False):
    """Configuration for worktree creation."""

    branch: str  # Optional: Branch name for the worktree
    base: str  # Optional: Base ref/branch for the new branch


class WorkerConfig(TypedDict, total=False):
    """Configuration for a single worker."""

    project_path: Required[str]  # Required: Path to repo, or "auto" to use env var
    agent_type: str  # Optional: "claude" (default) or "codex". Don't specify unless user requests.
    name: str  # Optional: Worker name override. None = auto-pick from themed sets.
    annotation: str  # Optional: Tracking label (NOT sent to worker). For badges/branches only.
    bead: str  # Optional: Issue ID - THIS IS the worker's assignment if provided
    prompt: str  # Optional: Custom instructions - THIS IS the worker's task if provided
    skip_permissions: bool  # Optional: Default False
    use_worktree: bool  # Optional: Create isolated worktree (default True)
    worktree: WorktreeConfig  # Optional: Worktree settings (branch/base)


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register spawn_workers tool on the MCP server."""

    @mcp.tool()
    async def spawn_workers(
        ctx: Context[ServerSession, "AppContext"],
        workers: list[WorkerConfig],
        layout: Literal["auto", "new"] | None = None,
    ) -> dict:
        """
        Spawn Claude Code worker sessions.

        Creates worker sessions in the active terminal backend, each with its own pane
        (iTerm) or window (tmux), Claude instance, and optional worktree. Workers can be
        spawned into existing
        windows (layout="auto") or a fresh window (layout="new").

        **Layout Modes:**

        1. **"auto"** (default): Reuse existing claude-team windows.
           - Finds tabs with <4 panes that contain managed sessions
           - Splits new panes into available space
           - Falls back to new window if no space available
           - Incremental quad building: TL → TR → BL → BR

        2. **"new"**: Always create a new window.
           - 1 worker: single pane (full window)
           - 2 workers: vertical split (left/right)
           - 3 workers: triple vertical (left/middle/right)
           - 4 workers: quad layout (2x2 grid)

        **tmux note:**
           - Workers get their own tmux window in a per-project claude-team session.
           - layout is ignored for tmux.

        **WorkerConfig fields:**
            project_path: Required. Path to the repository.
                - Explicit path: Use this repo (e.g., "/path/to/repo")
                - "auto": Use CLAUDE_TEAM_PROJECT_DIR from environment

                **Note**: When using "auto", the project needs a `.mcp.json`:
                ```json
                {
                  "mcpServers": {
                    "claude-team": {
                      "command": "uvx",
                      "args": ["--from", "claude-team-mcp", "claude-team"],
                      "env": {"CLAUDE_TEAM_PROJECT_DIR": "${PWD}"}
                    }
                  }
                }
                ```
            agent_type: Which agent CLI to use (default "claude").
                - "claude": Claude Code CLI (Stop hook idle detection)
                - "codex": OpenAI Codex CLI (JSONL streaming idle detection)

                ⚠️ **IMPORTANT**: Do not specify this field unless explicitly requested by the user.
                The default agent type is used unless an override is required.
            use_worktree: Whether to create an isolated worktree (default True).
                - True: Creates worktree at <repo>/.worktrees/<bead>-<annotation>
                  or <repo>/.worktrees/<name>-<uuid>-<annotation>
                - False: Worker uses the repo directory directly (no isolation)
            worktree: Optional worktree configuration.
                - branch: Branch name for the worktree
                - base: Base ref/branch for the new branch
            name: Optional worker name override. Leaving this empty allows us to auto-pick names
                from themed sets (Beatles, Marx Brothers, etc.) which aids visual identification.
            annotation: Optional task label for coordinator tracking. NOT sent to worker.
                Used for: badge display (2nd line), branch names, and list_workers output.
                This is metadata for YOUR reference, not task instructions for the worker.
                If using a bead, it's recommended to use the bead title as the annotation
                for clarity. Truncated to 30 chars in badge.
            bead: Optional beads issue ID. If provided, this IS the worker's assignment.
                The worker receives beads workflow instructions (mark in_progress, close,
                commit with issue reference). Used for badge first line and branch naming.
            prompt: Optional additional instructions. Combined with standard worker prompt,
                not a replacement. Use for extra context beyond what the bead describes.
            skip_permissions: Whether to start Claude with --dangerously-skip-permissions.
                Default False. Without this, workers can only read local files and will
                struggle with most commands (writes, shell, etc.).

        **Worker Assignment (how workers know what to do):**

        ⚠️ **IMPORTANT**: Tasks are delivered via `bead` and/or `prompt` parameters ONLY.
        The `annotation` parameter is never sent to workers - it's just metadata for
        coordinator tracking (badges, branches, list output).

        The worker's task is determined by `bead` and/or `prompt`:

        1. **bead only**: Worker assigned to the bead. They'll `bd show <bead>` for details
           and follow the beads workflow (mark in_progress → implement → close → commit).

        2. **bead + prompt**: Worker assigned to bead with additional instructions.
           Gets both the beads workflow and your custom guidance.

        3. **prompt only**: Worker assigned a custom task (no beads tracking).
           Your prompt text is their assignment.

        4. **neither**: Worker spawns idle, waiting for you to message them.
           ⚠️ Returns a warning reminding you to send them a task immediately.

        **Badge Format:**
        ```
        <bead or name>
        <annotation (truncated)>
        ```

        Args:
            workers: List of WorkerConfig dicts. Must have 1-4 workers.
            layout: "auto" (reuse windows) or "new" (fresh window).

        Returns:
            Dict with:
                - sessions: Dict mapping worker names to session info
                - layout: The layout mode used
                - count: Number of workers spawned
                - coordinator_guidance: Per-worker summary with assignments and coordination reminder
                - workers_awaiting_task: (only if any) List of worker names needing tasks

        Example (bead assignment with auto worktrees):
            spawn_workers(
                workers=[
                    {"project_path": "auto", "bead": "cic-abc", "annotation": "Fix auth bug"},
                    {"project_path": "auto", "bead": "cic-xyz", "annotation": "Add unit tests"},
                ],
                layout="auto",
            )

        Example (custom prompt, no bead):
            spawn_workers(
                workers=[
                    {"project_path": "/path/to/repo", "prompt": "Review auth module for security issues"},
                ],
            )

        Example (spawn idle worker, send task separately):
            # Returns warning: "WORKERS NEED TASKS: Groucho..."
            result = spawn_workers(
                workers=[{"project_path": "/path/to/repo"}],
            )
            # Then immediately:
            message_workers(session_ids=["Groucho"], message="Your task is...")
        """
        from ..session_state import (
            await_codex_marker_in_jsonl,
            await_marker_in_jsonl,
            generate_marker_message,
        )

        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Load config and apply defaults
        try:
            config = load_config()
        except ConfigError as exc:
            logger.warning("Invalid config file; using defaults: %s", exc)
            config = default_config()
        defaults = config.defaults

        # Resolve layout from config if not explicitly provided
        if layout is None:
            layout = defaults.layout

        # Validate worker count
        if not workers:
            return error_response("At least one worker is required")
        if len(workers) > MAX_PANES_PER_TAB:
            return error_response(
                f"Maximum {MAX_PANES_PER_TAB} workers per spawn",
                hint="Call spawn_workers multiple times for more workers",
            )

        # Ensure all workers have required fields
        for i, w in enumerate(workers):
            if "project_path" not in w:
                return error_response(f"Worker {i} missing required 'project_path'")

        # Ensure we have a fresh backend connection/state
        backend = await ensure_connection(app_ctx)

        try:
            # Get base session index for color generation
            base_index = registry.count()

            # Resolve worker names: use provided names or auto-pick from themed sets
            worker_count = len(workers)
            resolved_names: list[str] = []

            # Count how many need auto-picked names
            unnamed_count = sum(1 for w in workers if not w.get("name"))

            # Get auto-picked names for workers without explicit names
            if unnamed_count > 0:
                _, auto_names = pick_names_for_count(unnamed_count)
                auto_name_iter = iter(auto_names)
            else:
                auto_name_iter = iter([])  # Empty iterator

            for w in workers:
                name = w.get("name")
                if name:
                    resolved_names.append(name)
                else:
                    resolved_names.append(next(auto_name_iter))

            # Resolve project paths and create worktrees if needed
            resolved_paths: list[str] = []
            worktree_paths: dict[int, Path] = {}  # index -> worktree path
            main_repo_paths: dict[int, Path] = {}  # index -> main repo
            worktree_warnings: list[str] = []

            # Get CLAUDE_TEAM_PROJECT_DIR for "auto" paths
            env_project_dir = os.environ.get("CLAUDE_TEAM_PROJECT_DIR")

            for i, (w, name) in enumerate(zip(workers, resolved_names)):
                project_path = w["project_path"]
                # Use config default when not explicitly set
                use_worktree = w.get("use_worktree")
                if use_worktree is None:
                    use_worktree = defaults.use_worktree
                worktree_config = w.get("worktree")
                worktree_explicitly_requested = worktree_config is not None
                worktree_branch = None
                worktree_base = None
                bead = w.get("bead")
                annotation = w.get("annotation")

                if worktree_config is not None:
                    if isinstance(worktree_config, dict):
                        worktree_branch = worktree_config.get("branch")
                        worktree_base = worktree_config.get("base")
                        use_worktree = True
                    elif isinstance(worktree_config, bool):
                        use_worktree = worktree_config
                    else:
                        return error_response(
                            f"Worker {i} has invalid 'worktree' configuration",
                            hint="Expected a dict with optional 'branch'/'base' fields or a boolean.",
                        )

                # Step 1: Resolve repo path
                if project_path == "auto":
                    if env_project_dir:
                        repo_path = Path(env_project_dir).resolve()
                    else:
                        return error_response(
                            "project_path='auto' requires CLAUDE_TEAM_PROJECT_DIR",
                            hint=(
                                "Add a .mcp.json to your project with: "
                                '"env": {"CLAUDE_TEAM_PROJECT_DIR": "${PWD}"}\n'
                                "Or use an explicit path."
                            ),
                        )
                else:
                    repo_path = Path(project_path).expanduser().resolve()
                    if not repo_path.is_dir():
                        return error_response(
                            f"Project path does not exist for worker {i}: {repo_path}",
                            hint=HINTS["project_path_missing"],
                        )

                # Step 2: Create worktree if requested (default True)
                if use_worktree:
                    try:
                        worktree_path = create_local_worktree(
                            repo_path=repo_path,
                            worker_name=name,
                            bead_id=bead,
                            annotation=annotation,
                            branch=worktree_branch,
                            base=worktree_base,
                        )
                        worktree_paths[i] = worktree_path
                        main_repo_paths[i] = repo_path
                        resolved_paths.append(str(worktree_path))
                        logger.info(f"Created local worktree for {name} at {worktree_path}")
                    except WorktreeError as e:
                        warning_message = (
                            f"Failed to create worktree for {name}: {e}. "
                            "Using repo directly."
                        )
                        if worktree_explicitly_requested:
                            return error_response(
                                warning_message,
                                hint=(
                                    "Verify the worktree branch/base settings and "
                                    "that the repository is in a clean state."
                                ),
                            )
                        logger.warning(warning_message)
                        worktree_warnings.append(warning_message)
                        resolved_paths.append(str(repo_path))
                else:
                    # No worktree - use repo directly
                    resolved_paths.append(str(repo_path))

            # Pre-generate session IDs for Stop hook injection
            session_ids = [str(uuid.uuid4())[:8] for _ in workers]

            # Pre-calculate agent types for each worker (needed by profile customizations
            # and agent startup)
            agent_types: list[str] = []
            for w in workers:
                # Use config default when not explicitly set
                agent_type = w.get("agent_type")
                if agent_type is None:
                    agent_type = defaults.agent_type
                agent_types.append(agent_type)

            # Build profile customizations for each worker (iTerm-only)
            profile_customizations: list[object | None] = [None] * worker_count
            if isinstance(backend, ItermBackend):
                from iterm2.profile import LocalWriteOnlyProfile

                profile_customizations = []
                for i, (w, name) in enumerate(zip(workers, resolved_names)):
                    customization = LocalWriteOnlyProfile()

                    bead = w.get("bead")
                    annotation = w.get("annotation")
                    agent_type = agent_types[i]

                    # Tab title
                    tab_title = format_session_title(
                        name, issue_id=bead, annotation=annotation
                    )
                    customization.set_name(tab_title)

                    # Tab color (unique per worker)
                    color = generate_tab_color(base_index + i)
                    customization.set_tab_color(color)
                    customization.set_use_tab_color(True)

                    # Badge (multi-line with bead/name, annotation, and agent type indicator)
                    badge_text = format_badge_text(
                        name, bead=bead, annotation=annotation, agent_type=agent_type
                    )
                    customization.set_badge_text(badge_text)

                    # Apply current appearance mode colors
                    await apply_appearance_colors(customization, backend.connection)

                    profile_customizations.append(customization)

            # Create panes based on layout mode
            pane_sessions: list = []  # list of terminal handles

            if backend.backend_id == "tmux":
                for i in range(worker_count):
                    pane_sessions.append(
                        await backend.create_session(
                            name=resolved_names[i],
                            project_path=resolved_paths[i],
                            issue_id=workers[i].get("bead"),
                            coordinator_annotation=workers[i].get("annotation"),
                        )
                    )
            elif layout == "auto":
                # Try to find an existing window where the ENTIRE batch fits.
                # This keeps spawn batches together rather than spreading across windows.
                reuse_window = False
                initial_pane_count = 0
                first_session = None  # Terminal handle to split from

                def _count_tmux_panes(target_session, sessions) -> int:
                    session_name = target_session.metadata.get("session_name")
                    window_index = target_session.metadata.get("window_index")
                    if not session_name or window_index is None:
                        return 1
                    return sum(
                        1
                        for session in sessions
                        if session.metadata.get("session_name") == session_name
                        and session.metadata.get("window_index") == window_index
                    )

                # Prefer the coordinator's window when running inside iTerm2.
                # ITERM_SESSION_ID format is "wXtYpZ:UUID" - extract just the UUID.
                iterm_session_env = os.environ.get("ITERM_SESSION_ID")
                coordinator_session_id = None
                if iterm_session_env and ":" in iterm_session_env:
                    coordinator_session_id = iterm_session_env.split(":", 1)[1]
                if coordinator_session_id and isinstance(backend, ItermBackend):
                    coordinator_handle = None
                    for session_handle in await backend.list_sessions():
                        if session_handle.native_id == coordinator_session_id:
                            coordinator_handle = session_handle
                            break

                    if coordinator_handle:
                        coordinator_window = await backend.get_window_for_handle(
                            coordinator_handle
                        )
                        if coordinator_window is not None:
                            native_session = backend.unwrap_session(coordinator_handle)
                            coordinator_tab = native_session.tab
                            if coordinator_tab is not None:
                                initial_pane_count = len(coordinator_tab.sessions)
                                available_slots = MAX_PANES_PER_TAB - initial_pane_count
                                if worker_count <= available_slots:
                                    reuse_window = True
                                    first_session = coordinator_handle
                                    logger.debug(
                                        "Using coordinator window "
                                        f"({initial_pane_count} panes, {available_slots} slots)"
                                    )

                if not reuse_window:
                    managed_session_ids = {
                        s.terminal_session.native_id
                        for s in registry.list_all()
                        if hasattr(s, 'terminal_session') and s.terminal_session.backend_id == backend.backend_id
                    }

                    # Find a window with enough space for ALL workers
                    result = await backend.find_available_window(
                        max_panes=MAX_PANES_PER_TAB,
                        managed_session_ids=managed_session_ids,
                    )

                    if result:
                        _, tab_or_window, existing_session = result
                        first_session = existing_session
                        if isinstance(backend, ItermBackend):
                            initial_pane_count = len(tab_or_window.sessions)
                        else:
                            initial_pane_count = _count_tmux_panes(
                                existing_session, await backend.list_sessions()
                            )
                        available_slots = MAX_PANES_PER_TAB - initial_pane_count

                        if worker_count <= available_slots:
                            # Entire batch fits in this window
                            reuse_window = True
                            logger.debug(
                                f"Batch of {worker_count} fits in existing window "
                                f"({initial_pane_count} panes, {available_slots} slots)"
                            )

                if reuse_window and first_session is not None:
                    # Reuse existing window - track pane count locally
                    local_pane_count = initial_pane_count
                    final_pane_count = initial_pane_count + worker_count
                    # Track created sessions for splitting
                    created_sessions: list = []

                    for i in range(worker_count):
                        # Choose layout strategy based on final pane count:
                        # - 3 panes: coordinator full left, workers stacked right
                        # - 4 panes: quad (TL→TR→BL→BR)
                        if final_pane_count == 3:
                            # Layout: coordinator | worker1
                            #                    |--------
                            #                    | worker2
                            if local_pane_count == 1:
                                # First split: vertical from coordinator
                                new_session = await backend.split_pane(
                                    first_session,
                                    vertical=True,
                                    before=False,
                                    profile=None,
                                    profile_customizations=profile_customizations[i],
                                )
                            else:
                                # Second split: horizontal from first worker (stack on right)
                                split_target = (
                                    created_sessions[0] if created_sessions else first_session
                                )
                                new_session = await backend.split_pane(
                                    split_target,
                                    vertical=False,
                                    before=False,
                                    profile=None,
                                    profile_customizations=profile_customizations[i],
                                )
                        else:
                            # Quad pattern: TL→TR(vsplit)→BL(hsplit)→BR(hsplit)
                            if local_pane_count == 1:
                                # First split: vertical (left/right)
                                new_session = await backend.split_pane(
                                    first_session,
                                    vertical=True,
                                    before=False,
                                    profile=None,
                                    profile_customizations=profile_customizations[i],
                                )
                            elif local_pane_count == 2:
                                # Second split: horizontal from left pane (bottom-left)
                                new_session = await backend.split_pane(
                                    first_session,
                                    vertical=False,
                                    before=False,
                                    profile=None,
                                    profile_customizations=profile_customizations[i],
                                )
                            else:  # local_pane_count == 3
                                # Third split: horizontal from right pane (bottom-right)
                                tr_session = (
                                    created_sessions[0] if created_sessions else first_session
                                )
                                new_session = await backend.split_pane(
                                    tr_session,
                                    vertical=False,
                                    before=False,
                                    profile=None,
                                    profile_customizations=profile_customizations[i],
                                )

                        pane_sessions.append(new_session)
                        created_sessions.append(new_session)
                        local_pane_count += 1
                else:
                    # No window with enough space for entire batch - create new window
                    logger.debug(
                        f"No window with space for batch of {worker_count}, creating new window"
                    )
                    # Use same layout logic as layout="new"
                    if worker_count == 1:
                        window_layout = "single"
                        pane_names = ["main"]
                    elif worker_count == 2:
                        window_layout = "vertical"
                        pane_names = ["left", "right"]
                    elif worker_count == 3:
                        window_layout = "triple_vertical"
                        pane_names = ["left", "middle", "right"]
                    else:  # 4
                        window_layout = "quad"
                        pane_names = ["top_left", "top_right", "bottom_left", "bottom_right"]

                    customizations_dict = None
                    if isinstance(backend, ItermBackend):
                        customizations_dict = {
                            pane_names[i]: profile_customizations[i]
                            for i in range(worker_count)
                        }

                    panes = await backend.create_multi_pane_layout(
                        window_layout,
                        profile=None,
                        profile_customizations=customizations_dict,
                    )

                    pane_sessions = [panes[name] for name in pane_names[:worker_count]]

            else:  # layout == "new"
                # Create new window with appropriate layout
                if worker_count == 1:
                    window_layout = "single"
                    pane_names = ["main"]
                elif worker_count == 2:
                    window_layout = "vertical"
                    pane_names = ["left", "right"]
                elif worker_count == 3:
                    window_layout = "triple_vertical"
                    pane_names = ["left", "middle", "right"]
                else:  # 4
                    window_layout = "quad"
                    pane_names = ["top_left", "top_right", "bottom_left", "bottom_right"]

                # Build customizations dict for layout
                customizations_dict = None
                if isinstance(backend, ItermBackend):
                    customizations_dict = {
                        pane_names[i]: profile_customizations[i]
                        for i in range(worker_count)
                    }

                panes = await backend.create_multi_pane_layout(
                    window_layout,
                    profile=None,
                    profile_customizations=customizations_dict,
                )

                pane_sessions = [panes[name] for name in pane_names[:worker_count]]

            # Start agent in all panes (both Claude and Codex)
            import asyncio
            async def start_agent_for_worker(index: int) -> None:
                session = pane_sessions[index]
                project_path = resolved_paths[index]
                worker_config = workers[index]
                marker_id = session_ids[index]
                agent_type = agent_types[index]

                # Check for worktree and set tracker env var if needed.
                tracker_info = get_worktree_tracker_dir(project_path)
                if tracker_info:
                    env_var, tracker_dir = tracker_info
                    env = {env_var: tracker_dir}
                else:
                    env = None

                cli = get_cli_backend(agent_type)
                stop_hook_marker_id = marker_id if agent_type == "claude" else None
                # Use config default when not explicitly set
                skip_permissions = worker_config.get("skip_permissions")
                if skip_permissions is None:
                    skip_permissions = defaults.skip_permissions
                await backend.start_agent_in_session(
                    handle=session,
                    cli=cli,
                    project_path=project_path,
                    dangerously_skip_permissions=skip_permissions,
                    env=env,
                    stop_hook_marker_id=stop_hook_marker_id,
                )

            await asyncio.gather(*[start_agent_for_worker(i) for i in range(worker_count)])

            # Register all sessions
            managed_sessions = []
            for i in range(worker_count):
                managed = registry.add(
                    terminal_session=pane_sessions[i],
                    project_path=resolved_paths[i],
                    name=resolved_names[i],
                    session_id=session_ids[i],
                )
                # Set annotation from worker config (if provided)
                managed.coordinator_annotation = workers[i].get("annotation")
                # Set agent type
                managed.agent_type = agent_types[i]
                # Store worktree info if applicable
                if i in worktree_paths:
                    managed.worktree_path = worktree_paths[i]
                    managed.main_repo_path = main_repo_paths[i]
                managed_sessions.append(managed)

            # Send marker messages for JSONL correlation (Claude + Codex)
            for i, managed in enumerate(managed_sessions):
                iterm_session_id = None
                tmux_pane_ids = None
                if managed.terminal_session.backend_id == "iterm":
                    iterm_session_id = managed.terminal_session.native_id
                elif managed.terminal_session.backend_id == "tmux":
                    tmux_pane_ids = [managed.terminal_session.native_id]
                marker_message = generate_marker_message(
                    managed.session_id,
                    iterm_session_id=iterm_session_id,
                    tmux_pane_ids=tmux_pane_ids,
                    project_path=(
                        managed.project_path if managed.agent_type == "codex" else None
                    ),
                )
                await backend.send_prompt_for_agent(
                    pane_sessions[i],
                    marker_message,
                    agent_type=managed.agent_type,
                    submit=True,
                )

            # Wait for markers to appear in JSONL (Claude and Codex)
            for i, managed in enumerate(managed_sessions):
                if managed.agent_type == "claude":
                    claude_session_id = await await_marker_in_jsonl(
                        managed.project_path,
                        managed.session_id,
                        timeout=30.0,
                        poll_interval=0.1,
                    )
                    if claude_session_id:
                        managed.claude_session_id = claude_session_id
                    else:
                        logger.warning(
                            f"Marker polling timed out for {managed.session_id}, "
                            "JSONL correlation unavailable"
                        )
                elif managed.agent_type == "codex":
                    # Poll for Codex marker and cache the JSONL path
                    codex_match = await await_codex_marker_in_jsonl(
                        managed.session_id,
                        timeout=30.0,
                        poll_interval=0.5,
                    )
                    if codex_match:
                        managed.codex_jsonl_path = codex_match.jsonl_path
                        logger.info(
                            f"Codex JSONL path cached for {managed.session_id}: "
                            f"{codex_match.jsonl_path}"
                        )
                    else:
                        logger.warning(
                            f"Codex marker polling timed out for {managed.session_id}, "
                            "JSONL correlation unavailable"
                        )

            # Send worker prompts - always use generate_worker_prompt with bead/custom_prompt
            workers_awaiting_task: list[str] = []  # Workers with no bead and no prompt
            for i, managed in enumerate(managed_sessions):
                worker_config = workers[i]
                bead = worker_config.get("bead")
                custom_prompt = worker_config.get("prompt")
                use_worktree = i in worktree_paths

                # Track workers that need immediate attention (case 4: no bead, no prompt)
                if not bead and not custom_prompt:
                    workers_awaiting_task.append(managed.name)

                tracker_path = (
                    str(managed.main_repo_path)
                    if managed.main_repo_path is not None
                    else managed.project_path
                )
                worker_prompt = generate_worker_prompt(
                    managed.session_id,
                    resolved_names[i],
                    agent_type=managed.agent_type,
                    use_worktree=use_worktree,
                    bead=bead,
                    project_path=tracker_path,
                    custom_prompt=custom_prompt,
                )

                # Send prompt to the already-running agent (both Claude and Codex)
                # Use agent-specific timing (Codex needs longer delay before Enter)
                logger.info(
                    "Sending prompt to %s (agent_type=%s, chars=%d)",
                    managed.name,
                    managed.agent_type,
                    len(worker_prompt),
                )
                await backend.send_prompt_for_agent(
                    pane_sessions[i],
                    worker_prompt,
                    agent_type=managed.agent_type,
                )
                logger.info(f"Prompt sent to {managed.name}")

            # Mark sessions ready
            result_sessions = {}
            for managed in managed_sessions:
                registry.update_status(managed.session_id, SessionStatus.READY)
                result_sessions[managed.name] = managed.to_dict()

            # Re-activate the window to bring it to focus
            if isinstance(backend, ItermBackend):
                try:
                    await backend.activate_app()
                    if pane_sessions:
                        await backend.activate_window_for_handle(pane_sessions[0])
                except Exception as e:
                    logger.debug(f"Failed to re-activate window: {e}")

            # Build worker summaries for coordinator guidance
            worker_summaries = []
            for i, name in enumerate(resolved_names):
                worker_config = workers[i]
                bead = worker_config.get("bead")
                custom_prompt = worker_config.get("prompt")
                awaiting = name in workers_awaiting_task

                worker_summaries.append({
                    "name": name,
                    "agent_type": agent_types[i],
                    "bead": bead,
                    "custom_prompt": custom_prompt,
                    "awaiting_task": awaiting,
                })

            # Build return value
            result = {
                "sessions": result_sessions,
                "layout": layout,
                "count": len(result_sessions),
                "coordinator_guidance": get_coordinator_guidance(worker_summaries),
            }

            # Add structured warning for programmatic access
            if workers_awaiting_task:
                result["workers_awaiting_task"] = workers_awaiting_task
            if worktree_warnings:
                result["warnings"] = worktree_warnings

            return result

        except ValueError as e:
            logger.error(f"Validation error in spawn_workers: {e}")
            return error_response(str(e))
        except Exception as e:
            logger.error(f"Failed to spawn workers: {e}")
            return error_response(
                str(e),
                hint=HINTS["iterm_connection"],
            )
