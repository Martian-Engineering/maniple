"""
Detect interactive launch blockers shown before an agent reaches its ready UI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LaunchBlocker:
    """Structured description of a launch blocker visible on screen."""

    slug: str
    summary: str
    hint: str
    auto_accept_choice: str | None = None


class AgentLaunchBlocked(RuntimeError):
    """Raised when an agent launch is blocked on an interactive confirmation UI."""

    def __init__(self, blocker: LaunchBlocker):
        self.blocker = blocker
        self.hint = blocker.hint
        super().__init__(blocker.summary)


_CLAUDE_BLOCKERS: tuple[tuple[tuple[str, ...], LaunchBlocker], ...] = (
    (
        ("New MCP server found in .mcp.json", "Use this and all future MCP servers"),
        LaunchBlocker(
            slug="mcp_trust_confirmation",
            summary=(
                "Claude launch is blocked on the project MCP trust prompt. "
                "Approve the MCP server in the worker terminal, then retry."
            ),
            hint=(
                "Open the worker pane and accept the .mcp.json server prompt "
                "once for this project, or remove/disable that MCP entry before spawning."
            ),
            auto_accept_choice="1",
        ),
    ),
    (
        ("WARNING: Claude Code running in Bypass Permissions mode", "Yes, I accept"),
        LaunchBlocker(
            slug="bypass_permissions_confirmation",
            summary=(
                "Claude launch is blocked on the Bypass Permissions confirmation. "
                "Accept it in the worker terminal, or disable skip_permissions for that worker."
            ),
            hint=(
                "Open the worker pane and confirm Bypass Permissions once, or set "
                "skip_permissions=False if you do not want that startup prompt."
            ),
            auto_accept_choice="2",
        ),
    ),
)


def detect_launch_blocker(content: str, engine_id: str) -> LaunchBlocker | None:
    """Return a known blocker if the current screen content matches one."""
    if engine_id != "claude":
        return None

    for needles, blocker in _CLAUDE_BLOCKERS:
        if all(needle in content for needle in needles):
            return blocker
    return None
