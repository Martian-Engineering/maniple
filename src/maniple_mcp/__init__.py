"""
Maniple MCP Server.

Temporary wrapper package while the repo is being renamed from
`claude_team_mcp` to `maniple_mcp`. See `docs/rename-decisions.md`.
"""


def main() -> None:
    """Console script entry point for the `maniple` CLI."""
    from claude_team_mcp import main as impl_main

    impl_main()


__all__ = ["main"]

