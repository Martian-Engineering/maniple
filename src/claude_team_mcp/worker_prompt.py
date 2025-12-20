"""Worker pre-prompt generation for coordinated team sessions."""

from typing import Optional


def generate_worker_prompt(
    session_id: str,
    name: str,
    use_worktree: bool = False,
    iterm_session_id: Optional[str] = None,
) -> str:
    """Generate the pre-prompt text for a worker session.

    Args:
        session_id: The unique identifier for this worker session
        name: The friendly name assigned to this worker
        use_worktree: Whether this worker is in an isolated worktree
        iterm_session_id: Optional iTerm2 session ID for discovery/recovery.
            When provided, an additional iTerm-specific marker is emitted
            to enable session recovery after MCP server restart.

    Returns:
        The formatted pre-prompt string to inject into the worker session
    """
    commit_section = ""
    if use_worktree:
        commit_section = """
5. **Commit when done.** You're in an isolated worktree branch — commit your
   completed work so it can be easily cherry-picked. Use a clear commit message
   summarizing what you did. Don't push; the coordinator handles that.
"""

    # iTerm-specific marker for session discovery/recovery
    # Future terminal support (e.g., Zed) will use their own marker format
    iterm_marker = ""
    if iterm_session_id:
        iterm_marker = f"\n<!claude-team-iterm:{iterm_session_id}!>"

    return f'''<!claude-team-session:{session_id}!>{iterm_marker}

Hey {name}! Welcome to the team.

You're part of a coordinated claude-team session. Your coordinator has tasks
for you. Do your best work — completion is detected automatically.

**Your session ID:** `{session_id}`

=== THE DEAL ===

1. **Do the work fully.** Either complete it or explain what's blocking you in
   your response. The coordinator reads your output to understand what happened.

2. **Beads discipline.** If you're working with beads for tracking:
   - `bd update <id> --status in_progress` when you start
   - `bd comment <id> "what you're doing"` as you go
   - **Never close beads** — that's the coordinator's job after review

3. **When you're done,** leave a clear summary in your response. Your completion
   is detected automatically — just finish your work and the system handles the rest.

4. **If blocked,** explain what you need in your response. The coordinator will
   read your conversation history and address it.
{commit_section}
=== TOOLS YOU'VE GOT ===
- `bd_help` — Quick reference for beads commands

Alright, you're all set. The coordinator will send your first task shortly.
'''


def get_coordinator_guidance(use_worktree: bool = False) -> str:
    """Get the coordinator guidance text to include in spawn_team response.

    Args:
        use_worktree: Whether workers are in isolated worktrees
    """
    worktree_line = ""
    if use_worktree:
        worktree_line = "\n- Commit when done (for easy cherry-picking back to main)"

    return f"""
=== YOU ARE THE COORDINATOR ===

Your team is ready. Here's what your workers know and what they expect from you:

**What workers have been told:**
- Do the work fully, or explain what's blocking in their response
- Comment on beads for progress, but NEVER close them
- You (the coordinator) review and close beads{worktree_line}

**Your responsibilities:**
1. **Assign clear tasks** — Workers will explain in their response if something's unclear
2. **Monitor workers** — Use `is_idle(session_id)` to check if they've finished
3. **Read their work** — Use `get_conversation_history(session_id)` to see what they did
4. **Annotate sessions** — Use `annotate_session(session_id, note)` to track assignments
5. **Review and close beads** — Workers comment progress; you verify and close

**Checking on workers:**
- `list_sessions` — See all workers and their status
- `is_idle(session_id)` — Check if a worker is idle (finished responding)
- `get_conversation_history(session_id)` — Read what a worker has been doing
- `get_session_status(session_id)` — Quick status check

**Idle detection:**
Worker completion is detected automatically via Stop hooks.
- `is_idle(session_id)` — Check if a worker has finished (returns idle: true/false)
- `wait_for_idle(session_id, timeout=600)` — Block until worker finishes
- `wait_for_team_idle(session_ids, mode="all", timeout=600)` — Wait for team

The system knows the instant they finish responding — no markers needed.

**Coordination patterns (a spectrum):**

At one end: **Hands-off** — Dispatch tasks to workers, then continue your conversation
with the user. Check in on workers when the user asks, or prompt them occasionally
("Want me to check on the team?"). Use `is_idle` for quick polls.

At the other end: **Fully autonomous** — The user sets a goal, you break it into tasks
(probably via beads), dispatch workers, and use `wait_for_idle(session_id)` or
`wait_for_team_idle(session_ids)` to block until they finish. Read their conversation
history to understand what they did, then assign follow-up tasks or report results.

Most coordination falls somewhere in between. Match your approach to the user's preference
and the nature of the work — exploratory tasks favor hands-off, sequential pipelines
favor autonomous waits.

**The deal:** Workers do the work and explain their output. No markers needed.
You review everything before it's considered done.
"""
