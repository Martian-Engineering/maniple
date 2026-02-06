"""
Shared utilities for Claude Team MCP tools.
"""

from .constants import (
    CONVERSATION_PAGE_SIZE,
    ISSUE_TRACKER_HELP_TOOL,
    build_issue_tracker_help_text,
    build_issue_tracker_quick_commands,
    build_worker_message_hint,
)
from .errors import error_response, HINTS, get_session_or_error
from .worktree_detection import get_worktree_tracker_dir

__all__ = [
    "CONVERSATION_PAGE_SIZE",
    "ISSUE_TRACKER_HELP_TOOL",
    "build_issue_tracker_help_text",
    "build_issue_tracker_quick_commands",
    "build_worker_message_hint",
    "error_response",
    "HINTS",
    "get_session_or_error",
    "get_worktree_tracker_dir",
]
