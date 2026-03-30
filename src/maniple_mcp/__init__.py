"""
Maniple MCP Server

An MCP server that allows one Claude Code session to spawn and manage
a team of other Claude Code sessions via tmux + iTerm2.
"""

__version__ = "0.1.0"


def main():
    """Entry point for the CLI command."""
    from .server import main as server_main

    server_main()


__all__ = [
    "main",
]
