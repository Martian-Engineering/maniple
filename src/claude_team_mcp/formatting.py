"""
Formatting utilities for Claude Team MCP.

Provides functions for formatting session titles, badge text, and other
display strings used in iTerm2 tabs and UI badges.
"""

from typing import Optional


def format_session_title(
    session_name: str,
    issue_id: Optional[str] = None,
    task_desc: Optional[str] = None,
) -> str:
    """
    Format a session title for iTerm2 tab display.

    Creates a formatted title string combining session name, optional issue ID,
    and optional task description.

    Args:
        session_name: Session identifier (e.g., "worker-1")
        issue_id: Optional issue/ticket ID (e.g., "cic-3dj")
        task_desc: Optional task description (e.g., "profile module")

    Returns:
        Formatted title string.

    Examples:
        >>> format_session_title("worker-1", "cic-3dj", "profile module")
        '[worker-1] cic-3dj: profile module'

        >>> format_session_title("worker-2", task_desc="refactor auth")
        '[worker-2] refactor auth'

        >>> format_session_title("worker-3")
        '[worker-3]'
    """
    # Build the title in parts
    title_parts = [f"[{session_name}]"]

    if issue_id and task_desc:
        # Both issue ID and description: "issue_id: task_desc"
        title_parts.append(f"{issue_id}: {task_desc}")
    elif issue_id:
        # Only issue ID
        title_parts.append(issue_id)
    elif task_desc:
        # Only description
        title_parts.append(task_desc)

    return " ".join(title_parts)


def format_badge_text(
    issue_id: Optional[str] = None,
    task_desc: Optional[str] = None,
    max_length: int = 25,
) -> str:
    """
    Format abbreviated badge text for iTerm2 badge display.

    Creates a compact string suitable for display in an iTerm2 badge,
    truncating with ellipsis if necessary.

    Args:
        issue_id: Optional issue/ticket ID (e.g., "cic-3dj")
        task_desc: Optional task description (e.g., "profile module")
        max_length: Maximum length of the output string (default 25)

    Returns:
        Abbreviated badge text, truncated with "..." if needed.

    Examples:
        >>> format_badge_text("cic-3dj", "profile module", max_length=25)
        'cic-3dj: profile module'

        >>> format_badge_text("cic-3dj", "implement user authentication system", max_length=25)
        'cic-3dj: implement us...'

        >>> format_badge_text(task_desc="quick fix", max_length=25)
        'quick fix'

        >>> format_badge_text()
        ''
    """
    if max_length < 4:
        # Too short to meaningfully truncate
        max_length = 4

    # Build the full text
    if issue_id and task_desc:
        full_text = f"{issue_id}: {task_desc}"
    elif issue_id:
        full_text = issue_id
    elif task_desc:
        full_text = task_desc
    else:
        return ""

    # Truncate if necessary
    if len(full_text) <= max_length:
        return full_text

    # Reserve 3 characters for ellipsis
    truncated = full_text[: max_length - 3].rstrip()
    return f"{truncated}..."
