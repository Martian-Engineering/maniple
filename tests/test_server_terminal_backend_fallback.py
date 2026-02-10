import sys
import types

import pytest
from mcp.server.fastmcp import FastMCP

import maniple_mcp.server as server_module
from maniple_mcp.registry import SessionRegistry
from maniple_mcp.terminal_backends import TmuxBackend


def _install_fake_iterm2(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connect_error: Exception | None = None,
) -> None:
    """Install a minimal fake iterm2 module tree into sys.modules for testing."""

    async def async_get_app(_connection):  # pragma: no cover - simple stub
        return object()

    class Connection:
        @classmethod
        async def async_create(cls):  # pragma: no cover - simple stub
            if connect_error is not None:
                raise connect_error
            return object()

    iterm2_pkg = types.ModuleType("iterm2")
    iterm2_app = types.ModuleType("iterm2.app")
    iterm2_conn = types.ModuleType("iterm2.connection")
    iterm2_app.async_get_app = async_get_app
    iterm2_conn.Connection = Connection

    monkeypatch.setitem(sys.modules, "iterm2", iterm2_pkg)
    monkeypatch.setitem(sys.modules, "iterm2.app", iterm2_app)
    monkeypatch.setitem(sys.modules, "iterm2.connection", iterm2_conn)


@pytest.mark.asyncio
async def test_app_lifespan_falls_back_to_tmux_on_implicit_iterm_failure(monkeypatch):
    _install_fake_iterm2(monkeypatch, connect_error=RuntimeError("boom"))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("MANIPLE_TERMINAL_BACKEND", raising=False)
    monkeypatch.delenv("CLAUDE_TEAM_TERMINAL_BACKEND", raising=False)
    monkeypatch.setattr(server_module, "is_recovery_attempted", lambda: True)
    monkeypatch.setattr(server_module, "get_global_registry", lambda: SessionRegistry())
    monkeypatch.setattr(server_module.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)

    mcp = FastMCP("test")
    async with server_module.app_lifespan(mcp) as ctx:
        assert isinstance(ctx.terminal_backend, TmuxBackend)


@pytest.mark.asyncio
async def test_app_lifespan_raises_on_implicit_iterm_failure_when_tmux_missing(monkeypatch):
    _install_fake_iterm2(monkeypatch, connect_error=RuntimeError("boom"))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("MANIPLE_TERMINAL_BACKEND", raising=False)
    monkeypatch.delenv("CLAUDE_TEAM_TERMINAL_BACKEND", raising=False)
    monkeypatch.setattr(server_module, "is_recovery_attempted", lambda: True)
    monkeypatch.setattr(server_module, "get_global_registry", lambda: SessionRegistry())
    monkeypatch.setattr(server_module.shutil, "which", lambda name: None)

    mcp = FastMCP("test")
    with pytest.raises(RuntimeError, match="Could not connect to iTerm2"):
        async with server_module.app_lifespan(mcp):
            pass


@pytest.mark.asyncio
async def test_app_lifespan_does_not_fallback_when_iterm_explicit(monkeypatch):
    _install_fake_iterm2(monkeypatch, connect_error=RuntimeError("boom"))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("MANIPLE_TERMINAL_BACKEND", "iterm")
    monkeypatch.delenv("CLAUDE_TEAM_TERMINAL_BACKEND", raising=False)
    monkeypatch.setattr(server_module, "is_recovery_attempted", lambda: True)
    monkeypatch.setattr(server_module, "get_global_registry", lambda: SessionRegistry())
    monkeypatch.setattr(server_module.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)

    mcp = FastMCP("test")
    with pytest.raises(RuntimeError, match="Could not connect to iTerm2"):
        async with server_module.app_lifespan(mcp):
            pass

