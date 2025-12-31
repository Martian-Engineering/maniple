"""Worker pre-prompt generation for coordinated team sessions."""

from typing import Optional


def generate_worker_prompt(
    session_id: str,
    name: str,
    use_worktree: bool = False,
    bead: Optional[str] = None,
    custom_prompt: Optional[str] = None,
) -> str:
    """Generate the pre-prompt text for a worker session.

    Args:
        session_id: The unique identifier for this worker session
        name: The friendly name assigned to this worker
        use_worktree: Whether this worker is in an isolated worktree
        bead: Optional beads issue ID (if provided, this is the assignment)
        custom_prompt: Optional additional instructions from the coordinator

    Returns:
        The formatted pre-prompt string to inject into the worker session

    Note:
        The iTerm-specific marker for session recovery is emitted separately
        via generate_marker_message() in session_state.py, which is called
        before the worker prompt is sent.
    """
    # Build optional sections with dynamic numbering
    next_step = 4
    extra_sections = ""

    # Beads section (if bead provided)
    if bead:
        beads_section = f"""
{next_step}. **Beads workflow.** You're working on `{bead}`. Follow this workflow:
   - Mark in progress: `bd --no-db update {bead} --status in_progress`
   - Implement the changes
   - Close issue: `bd --no-db close {bead}`
   - Commit with issue reference: `git add -A && git commit -m "{bead}: <summary>"`

   Use `bd --no-db` for all beads commands (required in worktrees).
"""
        extra_sections += beads_section
        next_step += 1

    # Commit section (if worktree but beads section didn't already cover commit)
    if use_worktree and not bead:
        commit_section = f"""
{next_step}. **Commit when done.** You're in an isolated worktree branch — commit your
   completed work so it can be easily cherry-picked or merged. Use a clear
   commit message summarizing what you did. Don't push; the coordinator
   handles that.
"""
        extra_sections += commit_section

    # Closing/assignment section - 4 cases based on bead and custom_prompt
    if bead and custom_prompt:
        # Case 2: bead + custom instructions
        closing = f"""=== YOUR ASSIGNMENT ===

The coordinator assigned you `{bead}` (use `bd show {bead}` for details) and included
the following instructions:

{custom_prompt}

Get to work!"""
    elif bead:
        # Case 1: bead only
        closing = f"""=== YOUR ASSIGNMENT ===

Your assignment is `{bead}`. Use `bd show {bead}` for details. Get to work!"""
    elif custom_prompt:
        # Case 3: custom instructions only
        closing = f"""=== YOUR ASSIGNMENT ===

The coordinator assigned you the following task:

{custom_prompt}

Get to work!"""
    else:
        # Case 4: no bead, no instructions - coordinator will message shortly
        closing = "Alright, you're all set. The coordinator will send your first task shortly."

    return f'''Hey {name}! Welcome to the team.

You're part of a coordinated `claude-team` session. Your coordinator has tasks
for you. Do your best to complete the work you've been assigned autonomously.
However, if you have questions/comments/concerns for your coordinator, you can
ask a question in chat and end your turn. `claude-team` will automatically report
your session as idle to the coordinator so they can respond.

=== THE DEAL ===

1. **Do the work fully.** Either complete it or explain what's blocking you in
   your response. The coordinator reads your output to understand what happened.

2. **When you're done,** leave a clear summary in your response. Your completion
   wil be detected automatically — just finish your work and the system handles the rest.

3. **If blocked,** explain what you need in your response. The coordinator will
   read your conversation history and address it.
{extra_sections}
{closing}
'''


def get_coordinator_guidance(
    worker_summaries: list[dict],
) -> str:
    """Get the coordinator guidance text to include in spawn_workers response.

    Args:
        worker_summaries: List of dicts with keys:
            - name: Worker name
            - bead: Optional bead ID
            - custom_prompt: Optional custom instructions (truncated for display)
            - awaiting_task: True if worker has no bead and no prompt

    Returns:
        Formatted coordinator guidance string
    """
    # Build per-worker summary lines
    worker_lines = []
    for w in worker_summaries:
        name = w["name"]
        bead = w.get("bead")
        custom_prompt = w.get("custom_prompt")
        awaiting = w.get("awaiting_task", False)

        if awaiting:
            worker_lines.append(f"- **{name}**: ⚠️ AWAITING TASK — send them instructions now")
        elif bead and custom_prompt:
            # Truncate custom prompt for display
            short_prompt = custom_prompt[:50] + "..." if len(custom_prompt) > 50 else custom_prompt
            worker_lines.append(f"- **{name}**: `{bead}` + custom instructions: \"{short_prompt}\"")
        elif bead:
            worker_lines.append(f"- **{name}**: `{bead}` (beads workflow: mark in_progress → implement → close → commit)")
        elif custom_prompt:
            short_prompt = custom_prompt[:50] + "..." if len(custom_prompt) > 50 else custom_prompt
            worker_lines.append(f"- **{name}**: custom task: \"{short_prompt}\"")

    workers_section = "\n".join(worker_lines)

    return f"""=== TEAM DISPATCHED ===

{workers_section}

Workers will do the work and explain their output. If blocked, they'll say so.
You review everything before it's considered done.

**Coordination style reminder:** Match your approach to the task. Hands-off for exploratory
work (check in when asked), autonomous for pipelines (wait for completion, read logs, continue).

⚠️ **WORKTREE LIFECYCLE** — Workers with worktrees commit to ephemeral branches.
BEFORE closing workers:
1. Review their code changes (read_worker_logs or inspect worktree directly)
2. Merge or cherry-pick their commits to a persistent branch
3. THEN close workers

Closing workers with worktrees DESTROYS their branches. Unmerged commits will be orphaned.
"""
