"""
Claude Team MCP Server

An MCP server that allows one Claude Code session to spawn and manage
a team of other Claude Code sessions via iTerm2.
"""

__version__ = "0.1.0"


def main():
    """Entry point for the claude-team command."""
    from .server import run_server
    run_server()
