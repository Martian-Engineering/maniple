"""
Beads issue tracking tools and constants.

Provides bd_help tool and shared constants for beads integration.
"""

from mcp.server.fastmcp import FastMCP


# Hint appended to messages sent to workers
WORKER_MESSAGE_HINT = "\n\n---\n(Note: Use the `bd_help` tool for guidance on using beads to track progress and add comments.)"

# Condensed beads help text for workers
BEADS_HELP_TEXT = """# Beads Quick Reference

Beads is a lightweight issue tracker. Use it to track progress and communicate with the coordinator.

## Essential Commands

```bash
bd list                              # List all issues
bd ready                             # Show unblocked work
bd show <issue-id>                   # Show issue details
bd update <id> --status in_progress  # Mark as in-progress
bd comment <id> "message"            # Add progress note (IMPORTANT!)
bd close <id>                        # Close when complete
```

## Status Values
- `open` - Not started
- `in_progress` - Currently working
- `closed` - Complete

## Priority Levels
- `P0` - Critical
- `P1` - High
- `P2` - Medium
- `P3` - Low

## Types
- `task` - Standard work item
- `bug` - Something broken
- `feature` - New functionality
- `epic` - Large multi-task effort
- `chore` - Maintenance work

## As a Worker

**IMPORTANT**: You should NOT close beads unless explicitly told to. Instead:

1. Mark your issue as in-progress when starting:
   ```bash
   bd update <issue-id> --status in_progress
   ```

2. Add comments to document your progress:
   ```bash
   bd comment <issue-id> "Completed the API endpoint, now working on tests"
   bd comment <issue-id> "Found edge case - handling null values in response"
   ```

3. When finished, add a final summary comment:
   ```bash
   bd comment <issue-id> "COMPLETE: Implemented feature X. Changes in src/foo.py and tests/test_foo.py. Ready for review."
   ```

4. The coordinator will review and close the bead.

## Creating New Issues (if needed)

```bash
bd create --title "Bug: X doesn't work" --type bug --priority P1 --description "Details..."
```

## Searching

```bash
bd search "keyword"          # Search by text
bd list --status open        # Filter by status
bd list --type bug           # Filter by type
bd blocked                   # Show blocked issues
```
"""


def register_tools(mcp: FastMCP) -> None:
    """Register beads-related tools on the MCP server."""

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
