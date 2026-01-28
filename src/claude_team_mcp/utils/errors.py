"""
Error response helpers for Claude Team MCP tools.

Provides standardized error formatting and common hints for recovery.
"""

from ..registry import SessionRegistry, ManagedSession


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
        "Run list_workers to see available workers, or discover_workers "
        "to find orphaned terminal sessions that can be adopted"
    ),
    "project_path_missing": (
        "Verify the path exists. For git worktrees, check 'git worktree list'. "
        "Use an absolute path like '/Users/name/project'"
    ),
    "iterm_connection": (
        "Ensure iTerm2 is running and Python API is enabled: "
        "iTerm2 → Preferences → General → Magic → Enable Python API"
    ),
    "terminal_backend_required": (
        "This tool only supports the iTerm2 or tmux backends. "
        "Set CLAUDE_TEAM_TERMINAL_BACKEND=iterm or tmux, or run inside a supported terminal."
    ),
    "registry_empty": (
        "No workers are being managed. Use spawn_workers to create new workers, "
        "or discover_workers to find existing Claude sessions in a supported terminal"
    ),
    "no_jsonl_file": (
        "Claude may not have started yet or the session file doesn't exist. "
        "Wait a few seconds and try again, or check that Claude Code started "
        "successfully in the terminal"
    ),
    "project_path_detection_failed": (
        "Could not auto-detect project path from terminal. Provide project_path "
        "explicitly when calling adopt_worker"
    ),
    "session_busy": (
        "The session is currently processing. Wait for it to finish, or use "
        "force=True to close it anyway (may lose work)"
    ),
}


def get_session_or_error(
    registry: SessionRegistry,
    session_id: str,
) -> ManagedSession | dict:
    """
    Resolve a session by ID, returning error dict if not found.

    Args:
        registry: The session registry to search
        session_id: ID to resolve (supports session_id, terminal_id, or name)

    Returns:
        ManagedSession if found, or error dict with hint if not found
    """
    session = registry.resolve(session_id)
    if not session:
        return error_response(
            f"Session not found: {session_id}",
            hint=HINTS["session_not_found"],
        )
    return session
