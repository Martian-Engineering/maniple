"""Worker pre-prompt generation for coordinated team sessions."""

from typing import Literal, Optional

# Valid agent types for prompt generation
AgentType = Literal["claude", "codex"]


def generate_worker_prompt(
    session_id: str,
    name: str,
    *,
    agent_type: AgentType = "claude",
    use_worktree: bool = False,
    bead: Optional[str] = None,
    custom_prompt: Optional[str] = None,
) -> str:
    """Generate the pre-prompt text for a worker session.

    Args:
        session_id: The unique identifier for this worker session
        name: The friendly name assigned to this worker
        agent_type: The type of agent CLI ("claude" or "codex")
        use_worktree: Whether this worker is in an isolated worktree
        bead: Optional assignment ID used for labeling/assignment text
        custom_prompt: Optional additional instructions from the coordinator

    Returns:
        The formatted pre-prompt string to inject into the worker session

    Note:
        The iTerm-specific marker for session recovery is emitted separately
        via generate_marker_message() in session_state.py, which is called
        before the worker prompt is sent. This marker is only used for Claude
        workers since Codex doesn't parse JSONL markers.
    """
    if agent_type == "codex":
        return _generate_codex_worker_prompt(
            session_id=session_id,
            name=name,
            use_worktree=use_worktree,
            bead=bead,
            custom_prompt=custom_prompt,
        )
    # Default to Claude prompt for unknown agent types to maintain backward compatibility
    return _generate_claude_worker_prompt(
        session_id=session_id,
        name=name,
        use_worktree=use_worktree,
        bead=bead,
        custom_prompt=custom_prompt,
    )


def _generate_claude_worker_prompt(
    session_id: str,
    name: str,
    use_worktree: bool = False,
    bead: Optional[str] = None,
    custom_prompt: Optional[str] = None,
) -> str:
    """Generate the pre-prompt for a Claude Code worker session.

    Claude Code workers have access to:
    - claude-team MCP markers for session recovery
    - Stop hook idle detection
    - Full MCP tool ecosystem

    Args:
        session_id: The unique identifier for this worker session
        name: The friendly name assigned to this worker
        use_worktree: Whether this worker is in an isolated worktree
        bead: Optional assignment ID used for labeling/assignment text
        custom_prompt: Optional additional instructions

    Returns:
        Formatted pre-prompt for Claude worker
    """
    # Build optional sections with dynamic numbering
    next_step = 4
    extra_sections = ""

    # Commit section (if worktree)
    if use_worktree:
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

The coordinator assigned you `{bead}` and included the following instructions:

{custom_prompt}

Get to work!"""
    elif bead:
        # Case 1: bead only
        closing = f"""=== YOUR ASSIGNMENT ===

Your assignment is `{bead}`. Get to work!"""
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


def _generate_codex_worker_prompt(
    session_id: str,
    name: str,
    use_worktree: bool = False,
    bead: Optional[str] = None,
    custom_prompt: Optional[str] = None,
) -> str:
    """Generate the pre-prompt for an OpenAI Codex worker session.

    Codex workers differ from Claude:
    - No claude-team MCP markers (Codex doesn't parse JSONL markers)
    - No Stop hook idle detection (uses output pattern matching or timeouts)
    - Runs with --full-auto instead of --dangerously-skip-permissions

    Args:
        session_id: The unique identifier for this worker session
        name: The friendly name assigned to this worker
        use_worktree: Whether this worker is in an isolated worktree
        bead: Optional assignment ID used for labeling/assignment text
        custom_prompt: Optional additional instructions

    Returns:
        Formatted pre-prompt for Codex worker
    """
    # Build optional sections with dynamic numbering
    next_step = 4
    extra_sections = ""

    # Commit section (if worktree)
    if use_worktree:
        commit_section = f"""
{next_step}. **Commit when done.** You're in an isolated worktree branch — commit your
   completed work so it can be easily cherry-picked or merged. Use a clear
   commit message summarizing what you did. Don't push; the coordinator
   handles that.
"""
        extra_sections += commit_section

    # Closing/assignment section - 4 cases based on bead and custom_prompt
    if bead and custom_prompt:
        closing = f"""=== YOUR ASSIGNMENT ===

The coordinator assigned you `{bead}` and included the following instructions:

{custom_prompt}

Get to work!"""
    elif bead:
        closing = f"""=== YOUR ASSIGNMENT ===

Your assignment is `{bead}`. Get to work!"""
    elif custom_prompt:
        closing = f"""=== YOUR ASSIGNMENT ===

The coordinator assigned you the following task:

{custom_prompt}

Get to work!"""
    else:
        closing = "Alright, you're all set. The coordinator will send your first task shortly."

    # Codex prompt differs from Claude in key ways:
    # - No reference to claude-team MCP markers
    # - No "automatically report your session as idle" - Codex doesn't use stop hooks
    # - Simpler coordination model (output-based status checking)
    return f'''Hey {name}! Welcome to the team.

You're part of a coordinated multi-agent team. Your coordinator has tasks for you.
Do your best to complete the work you've been assigned autonomously.

If you have questions or concerns, clearly state them at the end of your response
and wait for further instructions. The coordinator will check your progress periodically.

=== THE DEAL ===

1. **Do the work fully.** Either complete it or explain what's blocking you.
   The coordinator reads your output to understand what happened.

2. **When you're done,** leave a clear summary of what you accomplished.
   End your response with "COMPLETED" or "BLOCKED: <reason>" so the coordinator
   can easily assess your status.

3. **If blocked,** explain what you need. The coordinator will read your output
   and address it.
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
            - agent_type: Agent type ("claude" or "codex")
            - bead: Optional bead ID
            - custom_prompt: Optional custom instructions (truncated for display)
            - awaiting_task: True if worker has no bead and no prompt

    Returns:
        Formatted coordinator guidance string
    """
    # Check if we have a mixed team
    agent_types = {w.get("agent_type", "claude") for w in worker_summaries}
    is_mixed_team = len(agent_types) > 1

    # Build per-worker summary lines
    worker_lines = []
    for w in worker_summaries:
        name = w["name"]
        agent_type = w.get("agent_type", "claude")
        bead = w.get("bead")
        custom_prompt = w.get("custom_prompt")
        awaiting = w.get("awaiting_task", False)

        # Add agent type indicator if mixed team
        type_indicator = f" [{agent_type}]" if is_mixed_team else ""

        if awaiting:
            worker_lines.append(
                f"- **{name}**{type_indicator}: "
                "AWAITING TASK - send them instructions now"
            )
        elif bead and custom_prompt:
            # Truncate custom prompt for display
            short_prompt = (
                custom_prompt[:50] + "..." if len(custom_prompt) > 50 else custom_prompt
            )
            worker_lines.append(
                f"- **{name}**{type_indicator}: `{bead}` + custom: \"{short_prompt}\""
            )
        elif bead:
            worker_lines.append(f"- **{name}**{type_indicator}: `{bead}` assignment")
        elif custom_prompt:
            short_prompt = (
                custom_prompt[:50] + "..." if len(custom_prompt) > 50 else custom_prompt
            )
            worker_lines.append(
                f"- **{name}**{type_indicator}: custom task: \"{short_prompt}\""
            )

    workers_section = "\n".join(worker_lines)

    # Build mixed team guidance if applicable
    mixed_team_section = ""
    if is_mixed_team:
        mixed_team_section = """
**Mixed team note:** You have both Claude and Codex workers:
- **Claude workers**: Idle detection via Stop hooks (automatic)
- **Codex workers**: Check status by reading their output for "COMPLETED" or "BLOCKED"
"""

    return f"""=== TEAM DISPATCHED ===

{workers_section}
{mixed_team_section}
Workers will do the work and explain their output. If blocked, they'll say so.
You review everything before it's considered done.

**Coordination style reminder:** Match your approach to the task. Hands-off for exploratory
work (check in when asked), autonomous for pipelines (wait for completion, read logs, continue).

**WORKTREE LIFECYCLE** — Workers with worktrees commit to ephemeral branches.
When you close workers:
1. Worktree directories are removed, but branches (and commits) are preserved
2. Review commits on worker branches before merging
3. Merge or cherry-pick to main, then delete the worker branch

Branches persist until explicitly deleted with `git branch -d <branch>`.
"""
