"""
Formatting utilities for Claude Team MCP.

Provides functions for formatting session titles, badge text, and other
display strings used in iTerm2 tabs and UI badges.
"""

from typing import Optional


def format_session_title(
    session_name: str,
    issue_id: Optional[str] = None,
    annotation: Optional[str] = None,
) -> str:
    """
    Format a session title for iTerm2 tab display.

    Creates a formatted title string combining session name, optional issue ID,
    and optional annotation.

    Args:
        session_name: Session identifier (e.g., "worker-1")
        issue_id: Optional issue/ticket ID (e.g., "cic-3dj")
        annotation: Optional task annotation (e.g., "profile module")

    Returns:
        Formatted title string.

    Examples:
        >>> format_session_title("worker-1", "cic-3dj", "profile module")
        '[worker-1] cic-3dj: profile module'

        >>> format_session_title("worker-2", annotation="refactor auth")
        '[worker-2] refactor auth'

        >>> format_session_title("worker-3")
        '[worker-3]'
    """
    # Build the title in parts
    title_parts = [f"[{session_name}]"]

    if issue_id and annotation:
        # Both issue ID and annotation: "issue_id: annotation"
        title_parts.append(f"{issue_id}: {annotation}")
    elif issue_id:
        # Only issue ID
        title_parts.append(issue_id)
    elif annotation:
        # Only annotation
        title_parts.append(annotation)

    return " ".join(title_parts)


def format_badge_text(
    name: str,
    bead: Optional[str] = None,
    annotation: Optional[str] = None,
    agent_type: Optional[str] = None,
    max_annotation_length: int = 30,
) -> str:
    """
    Format badge text with bead/name on first line, annotation on second.

    Creates a multi-line string suitable for iTerm2 badge display:
    - Line 1: Agent type prefix (if not "claude") + bead ID (if provided) or worker name
    - Line 2: annotation (if provided), truncated if too long

    Args:
        name: Worker name (used if bead not provided)
        bead: Optional bead/issue ID (e.g., "cic-3dj")
        annotation: Optional task annotation
        agent_type: Optional agent type ("claude" or "codex"). If "codex",
            adds a prefix to the first line.
        max_annotation_length: Maximum length for annotation line (default 30)

    Returns:
        Badge text, potentially multi-line.

    Examples:
        >>> format_badge_text("Groucho", "cic-3dj", "profile module")
        'cic-3dj\\nprofile module'

        >>> format_badge_text("Groucho", annotation="quick task")
        'Groucho\\nquick task'

        >>> format_badge_text("Groucho", "cic-3dj")
        'cic-3dj'

        >>> format_badge_text("Groucho")
        'Groucho'

        >>> format_badge_text("Groucho", annotation="a very long annotation here", max_annotation_length=20)
        'Groucho\\na very long annot...'

        >>> format_badge_text("Groucho", agent_type="codex")
        '[Codex] Groucho'

        >>> format_badge_text("Groucho", "cic-3dj", agent_type="codex")
        '[Codex] cic-3dj'
    """
    # First line: bead if provided, otherwise name
    first_line = bead if bead else name

    # Add agent type prefix for non-Claude agents
    if agent_type and agent_type != "claude":
        # Capitalize the agent type for display (e.g., "codex" -> "Codex")
        type_display = agent_type.capitalize()
        first_line = f"[{type_display}] {first_line}"

    # Second line: annotation if provided, with truncation
    if annotation:
        if len(annotation) > max_annotation_length:
            # Reserve 3 chars for ellipsis
            truncated = annotation[: max_annotation_length - 3].rstrip()
            annotation = f"{truncated}..."
        return f"{first_line}\n{annotation}"

    return first_line
