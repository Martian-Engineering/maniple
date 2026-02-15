"""
Formatting utilities for Claude Team MCP.

Provides functions for formatting session titles, badge text, and other
display strings used in iTerm2 tabs and UI badges.
"""

from typing import Optional


def format_session_title(
    session_name: str,
    issue_id: Optional[str] = None,
    badge: Optional[str] = None,
    *,
    annotation: Optional[str] = None,
) -> str:
    """
    Format a session title for iTerm2 tab display.

    Creates a formatted title string combining session name, optional issue ID,
    and optional badge text.

    Args:
        session_name: Session identifier (e.g., "worker-1")
        issue_id: Optional issue/ticket ID (e.g., "cic-3dj")
        badge: Optional task badge text (e.g., "profile module")
        annotation: Deprecated alias for badge (badge takes precedence)

    Returns:
        Formatted title string.

    Examples:
        >>> format_session_title("worker-1", "cic-3dj", "profile module")
        '[worker-1] cic-3dj: profile module'

        >>> format_session_title("worker-2", badge="refactor auth")
        '[worker-2] refactor auth'

        >>> format_session_title("worker-3")
        '[worker-3]'
    """
    # Build the title in parts
    title_parts = [f"[{session_name}]"]

    resolved_badge = badge if badge is not None else annotation

    if issue_id and resolved_badge:
        # Both issue ID and badge: "issue_id: badge"
        title_parts.append(f"{issue_id}: {resolved_badge}")
    elif issue_id:
        # Only issue ID
        title_parts.append(issue_id)
    elif resolved_badge:
        # Only badge
        title_parts.append(resolved_badge)

    return " ".join(title_parts)


def format_badge_text(
    name: str,
    issue_id: Optional[str] = None,
    badge: Optional[str] = None,
    agent_type: Optional[str] = None,
    max_badge_length: int = 30,
    *,
    annotation: Optional[str] = None,
    max_annotation_length: Optional[int] = None,
) -> str:
    """
    Format badge text with issue ID/name on first line, badge on second.

    Creates a multi-line string suitable for iTerm2 badge display:
    - Line 1: Agent type prefix (if not "claude") + issue ID (if provided) or worker name
    - Line 2: badge (if provided), truncated if too long

    Args:
        name: Worker name (used if issue_id not provided)
        issue_id: Optional issue/ticket ID (e.g., "cic-3dj")
        badge: Optional task badge text
        agent_type: Optional agent type ("claude" or "codex"). If "codex",
            adds a prefix to the first line.
        max_badge_length: Maximum length for badge line (default 30)
        annotation: Deprecated alias for badge (badge takes precedence)
        max_annotation_length: Deprecated alias for max_badge_length

    Returns:
        Badge text, potentially multi-line.

    Examples:
        >>> format_badge_text("Groucho", "cic-3dj", "profile module")
        'cic-3dj\\nprofile module'

        >>> format_badge_text("Groucho", badge="quick task")
        'Groucho\\nquick task'

        >>> format_badge_text("Groucho", "cic-3dj")
        'cic-3dj'

        >>> format_badge_text("Groucho")
        'Groucho'

        >>> format_badge_text("Groucho", badge="a very long badge here", max_badge_length=20)
        'Groucho\\na very long annot...'

        >>> format_badge_text("Groucho", agent_type="codex")
        '[Codex] Groucho'

        >>> format_badge_text("Groucho", "cic-3dj", agent_type="codex")
        '[Codex] cic-3dj'
    """
    resolved_badge = badge if badge is not None else annotation
    resolved_max_badge_length = (
        max_annotation_length if max_annotation_length is not None else max_badge_length
    )

    # First line: issue ID if provided, otherwise name
    first_line = issue_id if issue_id else name

    # Add agent type prefix for non-Claude agents
    if agent_type and agent_type != "claude":
        # Capitalize the agent type for display (e.g., "codex" -> "Codex")
        type_display = agent_type.capitalize()
        first_line = f"[{type_display}] {first_line}"

    # Second line: badge if provided, with truncation
    if resolved_badge:
        if len(resolved_badge) > resolved_max_badge_length:
            # Reserve 3 chars for ellipsis
            truncated = resolved_badge[: resolved_max_badge_length - 3].rstrip()
            resolved_badge = f"{truncated}..."
        return f"{first_line}\n{resolved_badge}"

    return first_line
