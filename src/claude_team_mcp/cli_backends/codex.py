"""
OpenAI Codex CLI backend.

Implements the AgentCLI protocol for OpenAI's Codex CLI.
This is a basic implementation - full integration will be done in later tasks.

Codex CLI reference: https://github.com/openai/codex
"""

import os
from typing import Literal

from .base import AgentCLI


class CodexCLI(AgentCLI):
    """
    OpenAI Codex CLI implementation.

    Note: This is a basic structure. Full Codex integration (ready detection,
    idle detection, etc.) will be implemented in later tasks (cic-f7w.3+).

    Codex CLI characteristics:
    - Uses `codex` command
    - Has --full-auto flag for non-interactive mode
    - No known Stop hook equivalent (may need JSONL streaming or timeouts)
    """

    @property
    def engine_id(self) -> str:
        """Return 'codex' as the engine identifier."""
        return "codex"

    def command(self) -> str:
        """
        Return the Codex CLI command.

        Respects CLAUDE_TEAM_CODEX_COMMAND environment variable for overrides
        (e.g., "happy codex" wrapper).
        """
        return os.environ.get("CLAUDE_TEAM_CODEX_COMMAND", "codex")

    def build_args(
        self,
        *,
        dangerously_skip_permissions: bool = False,
        settings_file: str | None = None,
    ) -> list[str]:
        """
        Build Codex CLI arguments.

        Args:
            dangerously_skip_permissions: Maps to --full-auto for Codex
            settings_file: Ignored - Codex doesn't support settings injection

        Returns:
            List of CLI arguments
        """
        args: list[str] = []

        # Codex uses --full-auto instead of --dangerously-skip-permissions
        if dangerously_skip_permissions:
            args.append("--full-auto")

        # Note: settings_file is ignored - Codex doesn't support this
        # If needed, alternative completion detection will be implemented
        # in later tasks (cic-f7w.3)

        return args

    def ready_patterns(self) -> list[str]:
        """
        Return patterns indicating Codex CLI is ready.

        TODO: These are placeholder patterns. Need to verify actual
        Codex CLI startup output in cic-f7w.3.
        """
        return [
            "codex>",  # Assumed prompt pattern
            "Ready",  # Common ready indicator
            ">",  # Generic prompt
        ]

    def idle_detection_method(self) -> Literal["stop_hook", "jsonl_stream", "none"]:
        """
        Codex idle detection method.

        Codex outputs JSONL events to stdout which are captured via tee
        when spawning workers. The idle_detection module's is_codex_idle()
        parses these events to detect TurnCompleted/TurnFailed events.
        """
        return "jsonl_stream"

    def supports_settings_file(self) -> bool:
        """
        Codex doesn't support --settings for hook injection.

        Alternative completion detection methods will be needed.
        """
        return False

    def build_resume_command(
        self,
        thread_id: str,
        message: str,
        *,
        full_auto: bool = False,
        output_jsonl_path: str | None = None,
    ) -> str:
        """
        Build a command to resume a Codex session with a new message.

        Creates a shell command that pipes the message to `codex exec resume`.
        Uses heredoc for multi-line messages to preserve formatting.

        Args:
            thread_id: The thread ID to resume
            message: The message/prompt to send
            full_auto: If True, add --full-auto flag
            output_jsonl_path: If provided, pipe output through tee to this file

        Returns:
            Complete shell command string ready for execution

        Example output:
            cat <<'EOF' | codex exec --full-auto resume abc123 - | tee /path/to/output.jsonl
            Your message here
            EOF
        """
        cmd = self.command()

        # Build args list
        args = ["exec"]
        if full_auto:
            args.append("--full-auto")
        args.append("resume")
        args.append(thread_id)
        args.append("-")  # Read prompt from stdin

        full_cmd = f"{cmd} {' '.join(args)}"

        # Add tee for output capture if path provided
        if output_jsonl_path:
            full_cmd = f"{full_cmd} | tee {output_jsonl_path}"

        # Use heredoc to pipe the message - EOF marker with quotes prevents expansion
        # The heredoc preserves multi-line messages correctly
        heredoc_cmd = f"cat <<'EOF' | {full_cmd}\n{message}\nEOF"

        return heredoc_cmd


# Singleton instance for convenience
codex_cli = CodexCLI()
