"""Tests for spawn_workers config defaults."""

from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

import claude_team_mcp.session_state as session_state
from claude_team_mcp.config import ConfigError, DefaultsConfig, default_config
from claude_team_mcp.registry import SessionRegistry
from claude_team_mcp.terminal_backends.base import TerminalSession
from claude_team_mcp.tools import spawn_workers as spawn_workers_module


class FakeBackend:
    """Minimal tmux-like backend for spawn_workers tests."""

    backend_id = "tmux"

    def __init__(self) -> None:
        self.started = []
        self.prompts = []
        self.sessions = []

    async def create_session(
        self,
        name: str | None = None,
        *,
        project_path: str | None = None,
        issue_id: str | None = None,
        coordinator_annotation: str | None = None,
        profile: str | None = None,
        profile_customizations: object | None = None,
    ) -> TerminalSession:
        session = TerminalSession(
            backend_id=self.backend_id,
            native_id=f"session-{len(self.sessions)}",
            handle=None,
        )
        self.sessions.append(session)
        return session

    async def start_agent_in_session(
        self,
        handle: TerminalSession,
        cli: object,
        project_path: str,
        dangerously_skip_permissions: bool = False,
        env: dict[str, str] | None = None,
        stop_hook_marker_id: str | None = None,
        **kwargs,
    ) -> None:
        self.started.append({
            "handle": handle,
            "cli": cli,
            "project_path": project_path,
            "dangerously_skip_permissions": dangerously_skip_permissions,
            "env": env,
            "stop_hook_marker_id": stop_hook_marker_id,
        })

    async def send_prompt_for_agent(
        self,
        session: TerminalSession,
        text: str,
        agent_type: str = "claude",
        submit: bool = True,
    ) -> None:
        self.prompts.append({
            "session": session,
            "text": text,
            "agent_type": agent_type,
            "submit": submit,
        })


@pytest.mark.asyncio
async def test_spawn_workers_uses_config_defaults(tmp_path, monkeypatch):
    """spawn_workers should apply config defaults when fields are omitted."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="codex",
        skip_permissions=True,
        use_worktree=False,
        layout="new",
    )
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)

    seen_agent_types = []

    def fake_get_cli_backend(agent_type: str):
        seen_agent_types.append(agent_type)
        return f"cli:{agent_type}"

    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", fake_get_cli_backend)

    def fail_create_local_worktree(*args, **kwargs):
        raise AssertionError("create_local_worktree should not be called")

    monkeypatch.setattr(
        spawn_workers_module,
        "create_local_worktree",
        fail_create_local_worktree,
    )
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)

    prompt_calls = []

    def fake_generate_worker_prompt(*args, **kwargs):
        prompt_calls.append(kwargs.get("use_worktree"))
        return "PROMPT"

    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        fake_generate_worker_prompt,
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "get_coordinator_guidance",
        lambda *args, **kwargs: {"summary": "ok"},
    )

    async def fake_await_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(session_state, "generate_marker_message", lambda *args, **kwargs: "MARKER")

    backend = FakeBackend()
    registry = SessionRegistry()
    app_ctx = SimpleNamespace(registry=registry, backend=backend)

    async def ensure_connection(app_context):
        return app_context.backend

    mcp = FastMCP("test")
    spawn_workers_module.register_tools(mcp, ensure_connection)
    tool = mcp._tool_manager.get_tool("spawn_workers")
    assert tool is not None

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_ctx))
    result = await tool.run({
        "workers": [{"project_path": str(repo_path), "name": "Worker1"}],
    }, context=ctx)

    assert result["layout"] == "new"
    assert seen_agent_types == ["codex"]
    assert backend.started[0]["dangerously_skip_permissions"] is True
    assert result["sessions"]["Worker1"]["agent_type"] == "codex"
    assert prompt_calls == [False]


@pytest.mark.asyncio
async def test_spawn_workers_invalid_config_falls_back(tmp_path, monkeypatch):
    """spawn_workers should fall back to defaults if config is invalid."""
    def raise_config_error():
        raise ConfigError("invalid config")

    monkeypatch.setattr(spawn_workers_module, "load_config", raise_config_error)

    seen_agent_types = []

    def fake_get_cli_backend(agent_type: str):
        seen_agent_types.append(agent_type)
        return f"cli:{agent_type}"

    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", fake_get_cli_backend)

    def fake_create_local_worktree(repo_path, **kwargs):
        return repo_path

    monkeypatch.setattr(
        spawn_workers_module,
        "create_local_worktree",
        fake_create_local_worktree,
    )
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)

    prompt_calls = []

    def fake_generate_worker_prompt(*args, **kwargs):
        prompt_calls.append(kwargs.get("use_worktree"))
        return "PROMPT"

    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        fake_generate_worker_prompt,
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "get_coordinator_guidance",
        lambda *args, **kwargs: {"summary": "ok"},
    )

    async def fake_await_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(session_state, "generate_marker_message", lambda *args, **kwargs: "MARKER")

    backend = FakeBackend()
    registry = SessionRegistry()
    app_ctx = SimpleNamespace(registry=registry, backend=backend)

    async def ensure_connection(app_context):
        return app_context.backend

    mcp = FastMCP("test")
    spawn_workers_module.register_tools(mcp, ensure_connection)
    tool = mcp._tool_manager.get_tool("spawn_workers")
    assert tool is not None

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_ctx))
    result = await tool.run({
        "workers": [{"project_path": str(repo_path), "name": "Worker1"}],
    }, context=ctx)

    assert result["layout"] == "auto"
    assert seen_agent_types == ["claude"]
    assert backend.started[0]["dangerously_skip_permissions"] is False
    assert result["sessions"]["Worker1"]["agent_type"] == "claude"
    assert prompt_calls == [True]
