"""Tests for the list_providers tool."""

from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from maniple_mcp.config import ConfigError, ProviderConfig, default_config
from maniple_mcp.tools import list_providers as list_providers_module


async def _run_tool(payload: dict | None = None):
    mcp = FastMCP("test")
    list_providers_module.register_tools(mcp)
    tool = mcp._tool_manager.get_tool("list_providers")
    assert tool is not None
    return await tool.run(payload or {}, context=SimpleNamespace())


async def test_list_providers_returns_sorted_provider_metadata(monkeypatch):
    """Configured providers should be returned in stable sorted order."""
    config = default_config()
    config.providers = {
        "kimi": ProviderConfig(
            command="/home/test/bin/claude-maniple-switch",
            env={"CLAUDE_SWITCH_PROVIDER": "kimi"},
        ),
        "aliyun": ProviderConfig(
            command="/home/test/bin/claude-maniple-switch",
            env={"CLAUDE_SWITCH_PROVIDER": "aliyun"},
        ),
    }
    monkeypatch.setattr(list_providers_module, "load_config", lambda: config)
    monkeypatch.setattr(
        list_providers_module,
        "resolve_config_path",
        lambda: "/home/test/.maniple/config.json",
    )

    result = await _run_tool()

    assert result["count"] == 2
    assert result["provider_names"] == ["aliyun", "kimi"]
    assert result["providers"] == [
        {
            "name": "aliyun",
            "command": "/home/test/bin/claude-maniple-switch",
            "env": {"CLAUDE_SWITCH_PROVIDER": "aliyun"},
        },
        {
            "name": "kimi",
            "command": "/home/test/bin/claude-maniple-switch",
            "env": {"CLAUDE_SWITCH_PROVIDER": "kimi"},
        },
    ]


async def test_list_providers_returns_error_for_invalid_config(monkeypatch):
    """Config validation failures should surface as tool errors."""
    monkeypatch.setattr(
        list_providers_module,
        "load_config",
        lambda: (_ for _ in ()).throw(ConfigError("bad config")),
    )
    monkeypatch.setattr(
        list_providers_module,
        "resolve_config_path",
        lambda: "/home/test/.maniple/config.json",
    )

    result = await _run_tool()

    assert result["error"] == "Invalid config: bad config"
    assert result["config_path"] == "/home/test/.maniple/config.json"
