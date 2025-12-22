"""
Beads help tool.

Provides bd_help for quick reference on beads issue tracking.
"""

from mcp.server.fastmcp import FastMCP

from ..utils import BEADS_HELP_TEXT


def register_tools(mcp: FastMCP) -> None:
    """Register bd_help tool on the MCP server."""

    @mcp.tool()
    async def bd_help() -> dict:
        """
        Get a quick reference guide for using Beads issue tracking.

        Returns condensed documentation on beads commands, workflow patterns,
        and best practices for worker sessions. Call this tool when you need
        guidance on tracking progress, adding comments, or managing issues.

        Returns:
            Dict with help text and key command examples
        """
        return {
            "help": BEADS_HELP_TEXT,
            "quick_commands": {
                "list_issues": "bd list",
                "show_ready": "bd ready",
                "show_issue": "bd show <issue-id>",
                "start_work": "bd update <id> --status in_progress",
                "add_comment": 'bd comment <id> "progress message"',
                "close_issue": "bd close <id>",
                "search": "bd search <query>",
            },
            "worker_tip": (
                "As a worker, add comments to track progress rather than closing issues. "
                "The coordinator will close issues after reviewing your work."
            ),
        }
