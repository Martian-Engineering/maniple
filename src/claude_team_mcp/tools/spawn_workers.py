"""
Spawn workers tool.

Provides spawn_workers for creating new Claude Code worker sessions.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Required, TypedDict

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from ..server import AppContext

from ..colors import generate_tab_color
from ..formatting import format_badge_text, format_session_title
from ..iterm_utils import (
    LAYOUT_PANE_NAMES,
    MAX_PANES_PER_TAB,
    create_multi_pane_layout,
    find_available_window,
    send_prompt,
    split_pane,
    start_claude_in_session,
)
from ..names import pick_names_for_count
from ..profile import (
    PROFILE_NAME,
    apply_appearance_colors,
    get_or_create_profile,
)
from ..registry import SessionStatus
from ..utils import BEADS_HELP_TEXT, HINTS, error_response, get_worktree_beads_dir
from ..worker_prompt import generate_worker_prompt, get_coordinator_guidance
from ..worktree import WorktreeError, create_local_worktree

logger = logging.getLogger("claude-team-mcp")


class WorkerConfig(TypedDict, total=False):
    """Configuration for a single worker."""

    project_path: Required[str]  # Required: Path or "auto" for local worktree
    name: str  # Optional: Worker name override. None = auto-pick from themed sets.
    annotation: str  # Optional: Task description (badge, branch, worker annotation)
    bead: str  # Optional: Beads issue ID (for badge, branch naming)
    prompt: str  # Optional: Custom prompt (None = standard worker prompt)
    skip_permissions: bool  # Optional: Default False


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register spawn_workers tool on the MCP server."""

    @mcp.tool()
    async def spawn_workers(
        ctx: Context[ServerSession, "AppContext"],
        workers: list[WorkerConfig],
        layout: Literal["auto", "new"] = "auto",
    ) -> dict:
        """
        Spawn Claude Code worker sessions.

        Creates worker sessions in iTerm2, each with its own pane, Claude instance,
        and optional worktree. Workers can be spawned into existing windows (layout="auto")
        or a fresh window (layout="new").

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

        **WorkerConfig fields:**
            project_path: Required. Path to project, or "auto" to create local worktree.
                - Path: Spawn worker at this location
                - "auto": Create worktree at .worktrees/<bead>-<annotation> or
                  .worktrees/<name>-<uuid>-<annotation>, auto-adds to .gitignore
            name: Optional worker name override. Leaving this empty allows us to auto-pick names
                from themed sets (Beatles, Marx Brothers, etc.) which aids visual identification.
            annotation: Optional task description. Shown on badge second line, used in
                branch names, and set as worker annotation. If using a bead, it's
                recommended to use the bead title as the annotation for clarity.
                Truncated to 30 chars in badge.
            bead: Optional beads issue ID. If provided, this IS the worker's assignment.
                The worker receives beads workflow instructions (mark in_progress, close,
                commit with issue reference). Used for badge first line and branch naming.
            prompt: Optional additional instructions. Combined with standard worker prompt,
                not a replacement. Use for extra context beyond what the bead describes.
            skip_permissions: Whether to start Claude with --dangerously-skip-permissions.
                Default False. Without this, workers can only read local files and will
                struggle with most commands (writes, shell, etc.).

        **Worker Assignment (how workers know what to do):**

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
        from iterm2.profile import LocalWriteOnlyProfile

        from ..session_state import await_marker_in_jsonl, generate_marker_message

        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

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

        # Ensure we have a fresh connection
        connection, app = await ensure_connection(app_ctx)

        try:
            # Ensure the claude-team profile exists
            await get_or_create_profile(connection)

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
            # Workers with project_path="auto" get local worktrees
            resolved_paths: list[str] = []
            worktree_paths: dict[int, Path] = {}  # index -> worktree path
            main_repo_paths: dict[int, Path] = {}  # index -> main repo (for "auto")

            # Find the main repo path for "auto" workers
            # Use the first non-auto path, or cwd
            main_repo_for_auto: Optional[Path] = None
            for w in workers:
                if w["project_path"] != "auto":
                    candidate = Path(w["project_path"]).expanduser().resolve()
                    if candidate.is_dir():
                        main_repo_for_auto = candidate
                        break
            if main_repo_for_auto is None:
                main_repo_for_auto = Path.cwd()

            for i, (w, name) in enumerate(zip(workers, resolved_names)):
                project_path = w["project_path"]

                if project_path == "auto":
                    # Create local worktree
                    bead = w.get("bead")
                    annotation = w.get("annotation")

                    try:
                        worktree_path = create_local_worktree(
                            repo_path=main_repo_for_auto,
                            worker_name=name,
                            bead_id=bead,
                            annotation=annotation,
                        )
                        worktree_paths[i] = worktree_path
                        main_repo_paths[i] = main_repo_for_auto
                        resolved_paths.append(str(worktree_path))
                        logger.info(f"Created local worktree for {name} at {worktree_path}")
                    except WorktreeError as e:
                        logger.warning(
                            f"Failed to create worktree for {name}: {e}. "
                            "Using main repo instead."
                        )
                        resolved_paths.append(str(main_repo_for_auto))
                else:
                    # Use provided path
                    resolved = os.path.abspath(os.path.expanduser(project_path))
                    if not os.path.isdir(resolved):
                        return error_response(
                            f"Project path does not exist for worker {i}: {resolved}",
                            hint=HINTS["project_path_missing"],
                        )
                    resolved_paths.append(resolved)

            # Pre-generate session IDs for Stop hook injection
            session_ids = [str(uuid.uuid4())[:8] for _ in workers]

            # Build profile customizations for each worker
            profile_customizations: list[LocalWriteOnlyProfile] = []
            for i, (w, name) in enumerate(zip(workers, resolved_names)):
                customization = LocalWriteOnlyProfile()

                bead = w.get("bead")
                annotation = w.get("annotation")

                # Tab title
                tab_title = format_session_title(name, issue_id=bead, annotation=annotation)
                customization.set_name(tab_title)

                # Tab color (unique per worker)
                color = generate_tab_color(base_index + i)
                customization.set_tab_color(color)
                customization.set_use_tab_color(True)

                # Badge (multi-line with bead/name and annotation)
                badge_text = format_badge_text(name, bead=bead, annotation=annotation)
                customization.set_badge_text(badge_text)

                # Apply current appearance mode colors
                await apply_appearance_colors(customization, connection)

                profile_customizations.append(customization)

            # Create panes based on layout mode
            pane_sessions: list = []  # list of iTerm sessions

            if layout == "auto":
                # Try to find existing windows with space
                # Build set of iTerm session IDs from all managed sessions
                managed_iterm_ids: set[str] = {
                    s.iterm_session.session_id
                    for s in registry.list_all()
                    if s.iterm_session is not None
                }

                for i in range(worker_count):
                    result = await find_available_window(
                        app,
                        max_panes=MAX_PANES_PER_TAB,
                        managed_session_ids=managed_iterm_ids,
                    )

                    if result:
                        # Found a window with space - split into it
                        window, tab, existing_session = result
                        current_pane_count = len(tab.sessions)

                        # Determine split direction based on current pane count
                        # Incremental quad: TL→TR(vsplit)→BL(hsplit)→BR(hsplit)
                        if current_pane_count == 1:
                            # First split: vertical (left/right)
                            new_session = await split_pane(
                                existing_session,
                                vertical=True,
                                before=False,
                                profile=PROFILE_NAME,
                                profile_customizations=profile_customizations[i],
                            )
                        elif current_pane_count == 2:
                            # Second split: horizontal from left pane (creates bottom-left)
                            # Get the left pane (first session)
                            left_session = tab.sessions[0]
                            new_session = await split_pane(
                                left_session,
                                vertical=False,
                                before=False,
                                profile=PROFILE_NAME,
                                profile_customizations=profile_customizations[i],
                            )
                        else:  # current_pane_count == 3
                            # Third split: horizontal from right pane (creates bottom-right)
                            # Get the right pane (second session after splits)
                            right_session = tab.sessions[1]
                            new_session = await split_pane(
                                right_session,
                                vertical=False,
                                before=False,
                                profile=PROFILE_NAME,
                                profile_customizations=profile_customizations[i],
                            )

                        pane_sessions.append(new_session)
                        # Update managed IDs for next iteration
                        managed_iterm_ids.add(new_session.session_id)
                    else:
                        # No window with space - create new window
                        # For the first worker when no windows exist, create a new window
                        if i == 0:
                            # Create new window with single pane
                            panes = await create_multi_pane_layout(
                                connection,
                                "single",
                                profile=PROFILE_NAME,
                                profile_customizations={"main": profile_customizations[i]},
                            )
                            pane_sessions.append(panes["main"])
                            managed_iterm_ids.add(panes["main"].session_id)
                        else:
                            # Subsequent workers when no space - split from last created
                            last_session = pane_sessions[-1]
                            new_session = await split_pane(
                                last_session,
                                vertical=True,
                                before=False,
                                profile=PROFILE_NAME,
                                profile_customizations=profile_customizations[i],
                            )
                            pane_sessions.append(new_session)
                            managed_iterm_ids.add(new_session.session_id)

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
                customizations_dict = {
                    pane_names[i]: profile_customizations[i] for i in range(worker_count)
                }

                panes = await create_multi_pane_layout(
                    connection,
                    window_layout,
                    profile=PROFILE_NAME,
                    profile_customizations=customizations_dict,
                )

                pane_sessions = [panes[name] for name in pane_names[:worker_count]]

            # Start Claude in all panes
            import asyncio

            async def start_claude_for_worker(index: int) -> None:
                session = pane_sessions[index]
                project_path = resolved_paths[index]
                worker_config = workers[index]
                marker_id = session_ids[index]

                # Check for worktree and set BEADS_DIR if needed
                beads_dir = get_worktree_beads_dir(project_path)
                env = {"BEADS_DIR": beads_dir} if beads_dir else None

                await start_claude_in_session(
                    session=session,
                    project_path=project_path,
                    dangerously_skip_permissions=worker_config.get("skip_permissions", False),
                    env=env,
                    stop_hook_marker_id=marker_id,
                )

            await asyncio.gather(*[start_claude_for_worker(i) for i in range(worker_count)])

            # Register all sessions
            managed_sessions = []
            for i in range(worker_count):
                managed = registry.add(
                    iterm_session=pane_sessions[i],
                    project_path=resolved_paths[i],
                    name=resolved_names[i],
                    session_id=session_ids[i],
                )
                # Set annotation from worker config (if provided)
                managed.coordinator_annotation = workers[i].get("annotation")
                # Store worktree info if applicable
                if i in worktree_paths:
                    managed.worktree_path = worktree_paths[i]
                    managed.main_repo_path = main_repo_paths[i]
                managed_sessions.append(managed)

            # Send marker messages for JSONL correlation
            for i, managed in enumerate(managed_sessions):
                marker_message = generate_marker_message(
                    managed.session_id,
                    iterm_session_id=managed.iterm_session.session_id,
                )
                await send_prompt(pane_sessions[i], marker_message, submit=True)

            # Wait for markers to appear in JSONL
            for i, managed in enumerate(managed_sessions):
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

                worker_prompt = generate_worker_prompt(
                    managed.session_id,
                    resolved_names[i],
                    use_worktree=use_worktree,
                    bead=bead,
                    custom_prompt=custom_prompt,
                )

                await send_prompt(pane_sessions[i], worker_prompt, submit=True)

            # Mark sessions ready
            result_sessions = {}
            for managed in managed_sessions:
                registry.update_status(managed.session_id, SessionStatus.READY)
                result_sessions[managed.name] = managed.to_dict()

            # Re-activate the window to bring it to focus
            try:
                await app.async_activate()
                if pane_sessions:
                    tab = pane_sessions[0].tab
                    if tab is not None:
                        window = tab.window
                        if window is not None:
                            await window.async_activate()
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
