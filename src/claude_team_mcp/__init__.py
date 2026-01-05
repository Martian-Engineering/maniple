"""
Claude Team MCP Server

An MCP server that allows one Claude Code session to spawn and manage
a team of other Claude Code sessions via iTerm2.
"""

__version__ = "0.1.0"

from .colors import generate_tab_color, get_hue_for_index, hsl_to_rgb_tuple


def main():
    """Entry point for the claude-team command."""
    from .server import main as server_main
    server_main()


__all__ = [
    "main",
    "generate_tab_color",
    "get_hue_for_index",
    "hsl_to_rgb_tuple",
]
