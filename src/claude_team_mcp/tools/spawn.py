"""
Worker spawning tools.

Provides spawn_workers for creating new Claude Code worker sessions.
"""

import hashlib
import logging
import os
import time
import uuid

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from ..colors import generate_tab_color
from ..formatting import format_session_title
from ..iterm_utils import (
    LAYOUT_PANE_NAMES,
    create_multi_claude_layout,
    send_prompt,
)
from ..names import pick_names_for_count
from ..profile import PROFILE_NAME, get_or_create_profile
from ..registry import SessionStatus
from ..worker_prompt import generate_worker_prompt, get_coordinator_guidance
from ..worktree import (
    WorktreeError,
    create_worktree,
)
from ..utils import error_response, HINTS, get_worktree_beads_dir
from .beads import BEADS_HELP_TEXT

logger = logging.getLogger("claude-team-mcp")


def register_tools(mcp: FastMCP, ensure_connection) -> None:
    """Register spawn-related tools on the MCP server."""

    @mcp.tool()
    async def spawn_workers(
        ctx: Context[ServerSession, "AppContext"],
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
            spawn_workers(
                projects={
                    "left": "/path/to/frontend",
                    "right": "/path/to/backend",
                },
                layout="vertical",
            )
            # Automatically picks a duo like Simon & Garfunkel or Tom & Jerry
            # Returns coordinator_guidance with worker management instructions

        Example (custom mode):
            spawn_workers(
                projects={"main": "/path/to/project"},
                layout="single",
                custom_prompt="You are a code reviewer. Review all changed files.",
                include_beads_instructions=False  # Skip beads for this workflow
            )
            # Workers receive your custom prompt, no coordinator_guidance returned
        """
        import iterm2

        from ..session_state import generate_marker_message, await_marker_in_jsonl
        from pathlib import Path

        app_ctx = ctx.request_context.lifespan_context
        registry = app_ctx.registry

        # Ensure we have a fresh connection (websocket can go stale)
        connection, app = await ensure_connection(app_ctx)

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
            profile_customizations: dict[str, iterm2.LocalWriteOnlyProfile] = {}
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
                    # Worktree name includes branch for identification
                    # Timestamp is added by create_worktree for uniqueness
                    worktree_name = f"{worker_name}-{short_hash}"
                    try:
                        # Worktrees are created at ~/.claude-team/worktrees/{repo-hash}/{name}-{timestamp}
                        # This keeps them outside the target repo to avoid "embedded repo" warnings
                        worktree_path = create_worktree(
                            repo_path=Path(project_path),
                            worktree_name=worktree_name,
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

                profile_customizations[pane_name] = customization

            # Create the multi-pane layout and start Claude in each pane
            # Pass pre-generated session IDs as marker IDs for Stop hook injection
            pane_sessions = await create_multi_claude_layout(
                connection=connection,
                projects=resolved_projects,
                layout=layout,
                skip_permissions=skip_permissions,
                project_envs=project_envs if project_envs else None,
                profile=PROFILE_NAME,
                profile_customizations=profile_customizations,
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
                # Store worktree path and main repo path if worktree was created
                if pane_name in worktree_paths:
                    managed.worktree_path = worktree_paths[pane_name]
                    managed.main_repo_path = Path(original_projects[pane_name])
                managed_sessions[pane_name] = managed

            # Send marker messages to all sessions for JSONL correlation
            for pane_name, managed in managed_sessions.items():
                marker_message = generate_marker_message(
                    managed.session_id,
                    iterm_session_id=managed.iterm_session.session_id,
                )
                await send_prompt(pane_sessions[pane_name], marker_message, submit=True)

            # Poll for markers to appear in JSONL (replaces blind 2s wait)
            # Marker is logged as user message the instant send_prompt returns
            for pane_name, managed in managed_sessions.items():
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

            # Determine mode and send appropriate prompts to workers
            is_standard_mode = custom_prompt is None

            for pane_name, managed in managed_sessions.items():
                iconic_name = pane_to_iconic[pane_name]

                if is_standard_mode:
                    # Standard mode: send worker pre-prompt with coordination workflow
                    # Note: iTerm marker already sent via generate_marker_message above
                    worker_prompt = generate_worker_prompt(
                        managed.session_id,
                        iconic_name,
                        use_worktree=use_worktrees,
                    )
                else:
                    # Custom mode: use the provided custom_prompt
                    worker_prompt = custom_prompt
                    if include_beads_instructions:
                        # Append beads guidance from BEADS_HELP_TEXT
                        worker_prompt += "\n\n---\n" + BEADS_HELP_TEXT

                await send_prompt(pane_sessions[pane_name], worker_prompt, submit=True)

            # Mark sessions ready (discovery already happened during marker polling)
            result_sessions = {}
            for pane_name, managed in managed_sessions.items():
                registry.update_status(managed.session_id, SessionStatus.READY)
                result_sessions[pane_name] = managed.to_dict()

            # Re-activate the window and app to bring it to focus after all setup is complete.
            # The initial activation in create_window() happens early, but focus can
            # shift back to the coordinator window during the Claude startup process.
            # Note: Window.async_activate() only focuses within iTerm2, we also need
            # App.async_activate() to bring iTerm2 itself to the foreground.
            try:
                await app.async_activate()
                # Get window from any of the sessions (they're all in the same window)
                any_session = next(iter(pane_sessions.values()))
                window = any_session.tab.window
                await window.async_activate()
            except Exception as e:
                logger.debug(f"Failed to re-activate window: {e}")

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
            logger.error(f"Validation error in spawn_workers: {e}")
            return error_response(str(e))
        except Exception as e:
            logger.error(f"Failed to spawn team: {e}")
            return error_response(
                str(e),
                hint=HINTS["iterm_connection"],
            )
