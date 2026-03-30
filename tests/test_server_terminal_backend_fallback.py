"""Tests for server terminal backend initialization."""

import pytest
from mcp.server.fastmcp import FastMCP

import maniple_mcp.server as server_module
from maniple_mcp.registry import SessionRegistry
from maniple_mcp.terminal_backends import TmuxBackend


@pytest.mark.asyncio
async def test_app_lifespan_always_creates_tmux_backend(monkeypatch):
    """Server always creates TmuxBackend (iTerm2 managed via ItermManager)."""
    monkeypatch.setattr(server_module, "is_recovery_attempted", lambda: True)
    monkeypatch.setattr(server_module, "get_global_registry", lambda: SessionRegistry())

    mcp = FastMCP("test")
    async with server_module.app_lifespan(mcp) as ctx:
        assert isinstance(ctx.terminal_backend, TmuxBackend)
