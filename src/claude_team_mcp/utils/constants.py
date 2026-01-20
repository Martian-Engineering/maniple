"""
Shared constants for Claude Team MCP tools.
"""

from pathlib import Path

from ..issue_tracker import BACKEND_REGISTRY, IssueTrackerBackend

# Default page size for conversation history pagination
CONVERSATION_PAGE_SIZE = 5

# Directory for Codex JSONL output capture
# Codex streams JSONL to stdout; we pipe it through tee to this directory
CODEX_JSONL_DIR = Path.home() / ".claude-team" / "codex"

# Tool name used for issue tracker help
ISSUE_TRACKER_HELP_TOOL = "issue_tracker_help"


def _format_tracker_command(
    backend: IssueTrackerBackend,
    command: str,
    **kwargs: str,
) -> str | None:
    """Format a tracker command template with the provided arguments."""
    template = backend.commands.get(command)
    if not template:
        return None
    return template.format(**kwargs)


def _supported_trackers_summary() -> str:
    """Return a comma-separated summary of known issue trackers."""
    return ", ".join(sorted(BACKEND_REGISTRY.keys()))


def build_issue_tracker_help_text(backend: IssueTrackerBackend | None) -> str:
    """Build issue tracker help text for the detected backend."""
    if backend is None:
        supported = _supported_trackers_summary()
        return (
            "# Issue Tracker Quick Reference\n\n"
            "No issue tracker detected for this project. "
            f"Supported trackers: {supported}.\n"
        )

    # Prepare command examples from the backend templates.
    list_cmd = _format_tracker_command(backend, "list") or ""
    ready_cmd = _format_tracker_command(backend, "ready") or ""
    show_cmd = _format_tracker_command(backend, "show", issue_id="<issue-id>") or ""
    update_cmd = (
        _format_tracker_command(
            backend,
            "update",
            issue_id="<issue-id>",
            status="in_progress",
        )
        or ""
    )
    # Worker-focused examples reuse the comment command template.
    comment_cmd = (
        _format_tracker_command(
            backend,
            "comment",
            issue_id="<issue-id>",
            comment="progress message",
        )
        or ""
    )
    comment_progress_cmd = (
        _format_tracker_command(
            backend,
            "comment",
            issue_id="<issue-id>",
            comment="Completed the API endpoint, now working on tests",
        )
        or ""
    )
    comment_final_cmd = (
        _format_tracker_command(
            backend,
            "comment",
            issue_id="<issue-id>",
            comment=(
                "COMPLETE: Implemented feature X. Changes in src/foo.py and "
                "tests/test_foo.py. Ready for review."
            ),
        )
        or ""
    )
    # Closing and creation examples round out the workflow guidance.
    close_cmd = _format_tracker_command(backend, "close", issue_id="<issue-id>") or ""
    create_cmd = (
        _format_tracker_command(
            backend,
            "create",
            title="Bug: X doesn't work",
            type="bug",
            priority="P1",
            description="Details...",
        )
        or ""
    )

    # Compose the full help text with backend-specific examples.
    return f"""# Issue Tracker Quick Reference

Your project uses the `{backend.name}` issue tracker. Use it to track progress and communicate with the coordinator.

## Essential Commands

```bash
{list_cmd}
{ready_cmd}
{show_cmd}
{update_cmd}
{comment_cmd}
{close_cmd}
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

1. Mark your issue as in-progress when starting:
   ```bash
   {update_cmd}
   ```

2. Add comments to document your progress:
   ```bash
   {comment_progress_cmd}
   ```

3. When finished, add a final summary comment:
   ```bash
   {comment_final_cmd}
   ```

4. The coordinator will review and close the issue.

## Creating New Issues (if needed)

```bash
{create_cmd}
```
"""


def build_issue_tracker_quick_commands(
    backend: IssueTrackerBackend | None,
) -> dict[str, str]:
    """Return quick command examples for the detected backend."""
    if backend is None:
        return {}

    # Map common actions to backend templates for quick reference.
    commands = {
        "list_issues": _format_tracker_command(backend, "list"),
        "show_ready": _format_tracker_command(backend, "ready"),
        "show_issue": _format_tracker_command(backend, "show", issue_id="<issue-id>"),
        "start_work": _format_tracker_command(
            backend,
            "update",
            issue_id="<issue-id>",
            status="in_progress",
        ),
        "add_comment": _format_tracker_command(
            backend,
            "comment",
            issue_id="<issue-id>",
            comment="progress message",
        ),
        "close_issue": _format_tracker_command(backend, "close", issue_id="<issue-id>"),
    }
    return {key: value for key, value in commands.items() if value}


def build_worker_message_hint(backend: IssueTrackerBackend | None) -> str:
    """Return the issue tracker hint appended to worker messages."""
    if backend is None:
        supported = _supported_trackers_summary()
        return (
            "\n\n---\n"
            f"(Note: Use the `{ISSUE_TRACKER_HELP_TOOL}` tool for guidance on the "
            f"configured issue tracker. Supported trackers: {supported}.)"
        )

    return (
        "\n\n---\n"
        f"(Note: Use the `{ISSUE_TRACKER_HELP_TOOL}` tool for guidance on "
        f"{backend.name} commands (CLI: `{backend.cli}`).)"
    )
