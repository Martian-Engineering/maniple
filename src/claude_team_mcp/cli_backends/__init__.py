"""
CLI Backends Module.

Provides abstraction layer for different agent CLI tools (Claude Code, Codex, etc.)
This allows claude-team to orchestrate multiple agent types through a unified interface.
"""

from .base import AgentCLI
from .claude import ClaudeCLI, claude_cli, get_claude_command
from .codex import CodexCLI, codex_cli, get_codex_command

__all__ = [
    "AgentCLI",
    "ClaudeCLI",
    "claude_cli",
    "get_claude_command",
    "CodexCLI",
    "codex_cli",
    "get_codex_command",
    "get_cli_backend",
]


def get_cli_backend(agent_type: str = "claude") -> AgentCLI:
    """
    Get a CLI backend instance by agent type.

    Args:
        agent_type: The agent type ("claude" or "codex")

    Returns:
        An AgentCLI implementation instance

    Raises:
        ValueError: If the agent type is not supported
    """
    backends = {
        "claude": claude_cli,
        "codex": codex_cli,
    }

    if agent_type not in backends:
        valid = ", ".join(sorted(backends.keys()))
        raise ValueError(f"Unknown agent type: {agent_type}. Valid types: {valid}")

    return backends[agent_type]
