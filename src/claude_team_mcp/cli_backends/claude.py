"""
Claude Code CLI backend.

Implements the AgentCLI protocol for Claude Code CLI.
This preserves the existing behavior from iterm_utils.py.
"""

import os
from typing import Literal

from .base import AgentCLI


class ClaudeCLI(AgentCLI):
    """
    Claude Code CLI implementation.

    Supports:
    - --dangerously-skip-permissions flag
    - --settings flag for Stop hook injection
    - Ready detection via TUI patterns (robot banner, '>' prompt, 'tokens' status)
    - Idle detection via Stop hook markers in JSONL
    """

    @property
    def engine_id(self) -> str:
        """Return 'claude' as the engine identifier."""
        return "claude"

    def command(self) -> str:
        """
        Return the Claude CLI command.

        Respects CLAUDE_TEAM_COMMAND environment variable for overrides
        (e.g., "happy" wrapper).
        """
        return os.environ.get("CLAUDE_TEAM_COMMAND", "claude")

    def build_args(
        self,
        *,
        dangerously_skip_permissions: bool = False,
        settings_file: str | None = None,
        resume_session_id: str | None = None,
        continue_session: bool = False,
        fork_session: bool = False,
    ) -> list[str]:
        """
        Build Claude CLI arguments.

        Args:
            dangerously_skip_permissions: Add --dangerously-skip-permissions
            settings_file: Path to settings JSON for Stop hook injection
            resume_session_id: Resume specific session by ID (--resume <id>)
            continue_session: Continue most recent session (--continue)
            fork_session: Fork instead of resume (--fork-session, use with --resume or --continue)

        Returns:
            List of CLI arguments

        Note:
            Claude Code CLI flags:
            - -c, --continue: Continue the most recent conversation
            - -r, --resume [value]: Resume by session ID or open picker
            - --fork-session: Create new session ID when resuming (use with --resume or --continue)
        """
        args: list[str] = []

        if dangerously_skip_permissions:
            args.append("--dangerously-skip-permissions")

        # Session resume/continue options (mutually exclusive modes)
        if resume_session_id:
            args.append("--resume")
            args.append(resume_session_id)
        elif continue_session:
            args.append("--continue")

        # Fork flag can be combined with resume or continue
        if fork_session and (resume_session_id or continue_session):
            args.append("--fork-session")

        # Only add --settings for the default 'claude' command.
        # Custom commands like 'happy' have their own session tracking mechanisms.
        # See HAPPY_INTEGRATION_RESEARCH.md for full analysis.
        if settings_file and self._is_default_command():
            args.append("--settings")
            args.append(settings_file)

        return args

    def ready_patterns(self) -> list[str]:
        """
        Return patterns indicating Claude TUI is ready.

        These patterns appear in Claude's startup:
        - '>' prompt indicates input ready
        - 'tokens' in status bar
        - Parts of the robot ASCII art banner
        """
        return [
            ">",  # Input prompt
            "tokens",  # Status bar
            "Claude Code v",  # Version line in banner
            "▐▛███▜▌",  # Top of robot head
            "▝▜█████▛▘",  # Middle of robot
        ]

    def idle_detection_method(self) -> Literal["stop_hook", "jsonl_stream", "none"]:
        """
        Claude uses Stop hook for idle detection.

        A Stop hook writes a marker to the JSONL when Claude finishes responding.
        """
        return "stop_hook"

    def supports_settings_file(self) -> bool:
        """
        Claude supports --settings for hook injection.

        Only returns True for the default 'claude' command.
        Custom wrappers may have their own settings mechanisms.
        """
        return self._is_default_command()

    def _is_default_command(self) -> bool:
        """Check if using the default 'claude' command (not a custom wrapper)."""
        cmd = os.environ.get("CLAUDE_TEAM_COMMAND", "claude")
        return cmd == "claude"


# Singleton instance for convenience
claude_cli = ClaudeCLI()
