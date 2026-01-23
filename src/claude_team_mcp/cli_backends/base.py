"""
Base protocol for CLI agent backends.

Defines the interface that all CLI backends (Claude, Codex, etc.) must implement.
This abstraction allows claude-team to orchestrate different agent CLIs.
"""

from abc import abstractmethod
from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class AgentCLI(Protocol):
    """
    Protocol defining the interface for agent CLI backends.

    Each implementation encapsulates the CLI-specific details:
    - Command and arguments
    - Ready detection patterns
    - Idle/completion detection method
    - Settings/hook injection support
    """

    @property
    @abstractmethod
    def engine_id(self) -> str:
        """
        Unique identifier for this CLI engine (e.g., "claude", "codex").

        Used for configuration, logging, and distinguishing between backends.
        """
        ...

    @abstractmethod
    def command(self) -> str:
        """
        Return the CLI executable name or path.

        Examples: "claude", "codex", "/usr/local/bin/custom-agent"
        """
        ...

    @abstractmethod
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
        Build the argument list for the CLI command.

        Args:
            dangerously_skip_permissions: If True, add flag to skip permission prompts
            settings_file: Optional path to settings file for hook injection
            resume_session_id: If provided, resume this specific session by ID
            continue_session: If True, continue the most recent session
            fork_session: If True, fork instead of resume (creates new session ID)

        Returns:
            List of command-line arguments (not including the command itself)

        Note:
            Session options (resume_session_id, continue_session, fork_session) are
            mutually exclusive with starting a fresh session. When any is provided,
            the CLI starts with existing conversation context.

            For Claude: uses -r/--resume, -c/--continue, --fork-session
            For Codex: uses subcommands (resume, fork) instead of flags
        """
        ...

    @abstractmethod
    def ready_patterns(self) -> list[str]:
        """
        Return patterns that indicate the CLI is ready for input.

        These patterns are searched for in terminal output to detect when
        the agent has started and is ready to receive prompts.

        Returns:
            List of strings to search for in terminal output
        """
        ...

    @abstractmethod
    def idle_detection_method(self) -> Literal["stop_hook", "jsonl_stream", "none"]:
        """
        Return the method used to detect when the agent finishes responding.

        - "stop_hook": Uses a Stop hook that fires when the agent completes
        - "jsonl_stream": Monitors JSONL output for completion markers
        - "none": No idle detection available (must use timeouts)

        Returns:
            The detection method identifier
        """
        ...

    @abstractmethod
    def supports_settings_file(self) -> bool:
        """
        Return whether this CLI supports --settings flag for hook injection.

        If False, build_args() should ignore the settings_file parameter.
        """
        ...

    def build_full_command(
        self,
        *,
        dangerously_skip_permissions: bool = False,
        settings_file: str | None = None,
        env_vars: dict[str, str] | None = None,
        resume_session_id: str | None = None,
        continue_session: bool = False,
        fork_session: bool = False,
    ) -> str:
        """
        Build the complete command string including env vars.

        This is a convenience method that combines command(), build_args(),
        and optional environment variables into a single shell command string.

        Args:
            dangerously_skip_permissions: Skip permission prompts
            settings_file: Settings file for hook injection
            env_vars: Environment variables to prepend
            resume_session_id: Resume a specific session by ID
            continue_session: Continue the most recent session
            fork_session: Fork instead of resume (creates new session ID)

        Returns:
            Complete command string ready for shell execution
        """
        cmd = self.command()
        args = self.build_args(
            dangerously_skip_permissions=dangerously_skip_permissions,
            settings_file=settings_file if self.supports_settings_file() else None,
            resume_session_id=resume_session_id,
            continue_session=continue_session,
            fork_session=fork_session,
        )

        if args:
            cmd = f"{cmd} {' '.join(args)}"

        if env_vars:
            env_exports = " ".join(f"{k}={v}" for k, v in env_vars.items())
            cmd = f"{env_exports} {cmd}"

        return cmd
