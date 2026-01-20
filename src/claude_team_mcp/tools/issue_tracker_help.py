"""
Issue tracker help tool.

Provides issue_tracker_help for quick reference on issue tracking commands.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..issue_tracker import BACKEND_REGISTRY, detect_issue_tracker
from ..utils import build_issue_tracker_help_text, build_issue_tracker_quick_commands


def register_tools(mcp: FastMCP) -> None:
    """Register issue_tracker_help tool on the MCP server."""

    @mcp.tool()
    async def issue_tracker_help() -> dict:
        """
        Get a quick reference guide for using issue tracking.

        Returns condensed documentation on tracker commands, workflow patterns,
        and best practices for worker sessions. Call this tool when you need
        guidance on tracking progress, adding comments, or managing issues.

        Returns:
            Dict with help text and key command examples
        """
        project_path = str(Path.cwd())
        backend = detect_issue_tracker(project_path)
        help_text = build_issue_tracker_help_text(backend)
        quick_commands = build_issue_tracker_quick_commands(backend)

        response = {
            "help": help_text,
            "quick_commands": quick_commands,
            "worker_tip": (
                "As a worker, add comments to track progress rather than closing issues. "
                "The coordinator will close issues after reviewing your work."
            ),
        }

        if backend is None:
            response["supported_trackers"] = sorted(BACKEND_REGISTRY.keys())
        else:
            response["tracker"] = backend.name
            response["cli"] = backend.cli

        return response
