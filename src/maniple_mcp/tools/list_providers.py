"""
Provider listing tool.

Provides list_providers for discovering configured worker launch providers.
"""

from mcp.server.fastmcp import FastMCP

from ..config import ConfigError, load_config, resolve_config_path
from ..utils import error_response


def register_tools(mcp: FastMCP) -> None:
    """Register list_providers tool on the MCP server."""

    @mcp.tool()
    async def list_providers() -> dict:
        """
        List configured worker launch providers from ~/.maniple/config.json.

        Useful for clients that want to discover which Claude-compatible
        provider presets are available before calling spawn_workers.

        Returns:
            Dict with provider names, command/env metadata, and config path
        """
        config_path = resolve_config_path()

        try:
            config = load_config()
        except ConfigError as exc:
            return error_response(
                f"Invalid config: {exc}",
                hint="Fix ~/.maniple/config.json and try again.",
                config_path=str(config_path),
            )

        providers = []
        for name in sorted(config.providers):
            provider = config.providers[name]
            providers.append({
                "name": name,
                "command": provider.command,
                "env": dict(sorted(provider.env.items())),
            })

        return {
            "config_path": str(config_path),
            "count": len(providers),
            "provider_names": [item["name"] for item in providers],
            "providers": providers,
            "usage_tip": (
                "Pass provider='<name>' in spawn_workers to launch a worker "
                "with one of these presets."
            ),
        }
