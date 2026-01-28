"""Tests for the tmux terminal backend."""

import subprocess

import pytest

from claude_team_mcp.terminal_backends.base import TerminalSession
from claude_team_mcp.terminal_backends.tmux import TMUX_SESSION_NAME, TmuxBackend


@pytest.mark.asyncio
async def test_send_text_uses_send_keys(monkeypatch):
    backend = TmuxBackend()
    calls = []

    async def fake_run(args):
        calls.append(args)
        return ""

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    session = TerminalSession("tmux", "%1", "%1")
    await backend.send_text(session, "hello")

    assert calls == [["send-keys", "-t", "%1", "-l", "hello"]]


@pytest.mark.asyncio
async def test_send_key_maps_ctrl_c(monkeypatch):
    backend = TmuxBackend()
    calls = []

    async def fake_run(args):
        calls.append(args)
        return ""

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    session = TerminalSession("tmux", "%2", "%2")
    await backend.send_key(session, "ctrl-c")

    assert calls == [["send-keys", "-t", "%2", "C-c"]]


@pytest.mark.asyncio
async def test_list_sessions_parses_panes(monkeypatch):
    backend = TmuxBackend()

    async def fake_run(args):
        assert args[:2] == ["list-panes", "-t"]
        assert args[2] == TMUX_SESSION_NAME
        return "s1\t@1\tworker-1\t0\t0\t%1\ns2\t@2\tworker-2\t1\t2\t%9\n"

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    sessions = await backend.list_sessions()
    assert len(sessions) == 2
    assert sessions[0].native_id == "%1"
    assert sessions[0].metadata["session_name"] == "s1"
    assert sessions[0].metadata["window_name"] == "worker-1"
    assert sessions[1].metadata["pane_index"] == "2"


@pytest.mark.asyncio
async def test_create_session_uses_tmux_commands(monkeypatch):
    backend = TmuxBackend()
    calls = []

    async def fake_run(args):
        calls.append(args)
        if args[:2] == ["has-session", "-t"]:
            raise subprocess.CalledProcessError(1, ["tmux"])
        if args[:2] == ["new-session", "-d"]:
            return "%7\t@7\t0"
        return ""

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    session = await backend.create_session("test-session")

    assert calls[0] == ["has-session", "-t", TMUX_SESSION_NAME]
    assert calls[1][:4] == ["new-session", "-d", "-s", TMUX_SESSION_NAME]
    assert session.native_id == "%7"
    assert session.metadata["session_name"] == TMUX_SESSION_NAME
    assert session.metadata["window_name"] == "test-session"


@pytest.mark.asyncio
async def test_find_available_window_prefers_active_pane(monkeypatch):
    backend = TmuxBackend()

    async def fake_run(args):
        assert args[:2] == ["list-panes", "-t"]
        assert args[2] == TMUX_SESSION_NAME
        return "s1\t@1\t0\t0\t0\t%1\ns1\t@1\t0\t1\t1\t%2\ns2\t@2\t0\t0\t1\t%3\n"

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    result = await backend.find_available_window(max_panes=3, managed_session_ids=None)

    assert result is not None
    session_name, window_index, session = result
    assert session_name == "s1"
    assert window_index == "0"
    assert session.native_id == "%2"
    assert session.metadata["pane_index"] == "1"


@pytest.mark.asyncio
async def test_find_available_window_respects_managed_filter(monkeypatch):
    backend = TmuxBackend()

    async def fake_run(args):
        assert args[:2] == ["list-panes", "-t"]
        assert args[2] == TMUX_SESSION_NAME
        return "s1\t@1\t0\t0\t1\t%1\ns1\t@1\t0\t1\t0\t%2\ns2\t@2\t1\t0\t1\t%3\n"

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    result = await backend.find_available_window(
        max_panes=4,
        managed_session_ids={"%3"},
    )

    assert result is not None
    session_name, window_index, session = result
    assert session_name == "s2"
    assert window_index == "1"
    assert session.native_id == "%3"


@pytest.mark.asyncio
async def test_find_available_window_returns_none_when_full(monkeypatch):
    backend = TmuxBackend()

    async def fake_run(args):
        assert args[:2] == ["list-panes", "-t"]
        assert args[2] == TMUX_SESSION_NAME
        return "s1\t@1\t0\t0\t1\t%1\ns1\t@1\t0\t1\t0\t%2\n"

    monkeypatch.setattr(backend, "_run_tmux", fake_run)

    result = await backend.find_available_window(max_panes=2)

    assert result is None
