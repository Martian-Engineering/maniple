"""Tests for spawn_workers config defaults."""

from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

import maniple_mcp.session_state as session_state
from maniple_mcp.config import ConfigError, DefaultsConfig, ProviderConfig, default_config
from maniple_mcp.launch_blockers import AgentLaunchBlocked, LaunchBlocker
from maniple_mcp.registry import SessionRegistry
from maniple_mcp.terminal_backends.base import TerminalSession
from maniple_mcp.tools import spawn_workers as spawn_workers_module


class FakeBackend:
    """Minimal tmux-like backend for spawn_workers tests."""

    backend_id = "tmux"

    def __init__(self) -> None:
        self.started = []
        self.prompts = []
        self.sessions = []
        self.create_calls = []
        self.raise_on_start = None

    async def create_session(
        self,
        name: str | None = None,
        *,
        project_path: str | None = None,
        issue_id: str | None = None,
        coordinator_badge: str | None = None,
        profile: str | None = None,
        profile_customizations: object | None = None,
    ) -> TerminalSession:
        self.create_calls.append({
            "name": name,
            "project_path": project_path,
            "issue_id": issue_id,
            "coordinator_badge": coordinator_badge,
        })
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
        if self.raise_on_start is not None:
            raise self.raise_on_start
        self.started.append({
            "handle": handle,
            "cli": cli,
            "project_path": project_path,
            "dangerously_skip_permissions": dangerously_skip_permissions,
            "env": env,
            "stop_hook_marker_id": stop_hook_marker_id,
            **kwargs,
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


async def _run_spawn_workers_tool(tmp_path, monkeypatch, backend, workers):
    config = default_config()
    config.defaults = DefaultsConfig(use_worktree=False, layout="new")
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda agent_type: f"cli:{agent_type}")
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "get_coordinator_guidance",
        lambda *args, **kwargs: {"summary": "ok"},
    )
    async def fake_await_marker_in_jsonl(*args, **kwargs):
        return None

    async def fake_await_codex_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(session_state, "await_codex_marker_in_jsonl", fake_await_codex_marker_in_jsonl)
    monkeypatch.setattr(session_state, "generate_marker_message", lambda *args, **kwargs: "MARKER")

    registry = SessionRegistry()
    app_ctx = SimpleNamespace(registry=registry, backend=backend)

    async def ensure_connection(app_context):
        return app_context.backend

    mcp = FastMCP("test")
    spawn_workers_module.register_tools(mcp, ensure_connection)
    tool = mcp._tool_manager.get_tool("spawn_workers")
    assert tool is not None

    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_ctx))
    return await tool.run({"workers": workers}, context=ctx)


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

    async def fake_await_codex_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(
        session_state,
        "await_codex_marker_in_jsonl",
        fake_await_codex_marker_in_jsonl,
    )
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
    assert backend.started[0]["env"] == {"CI": "1"}
    assert result["sessions"]["Worker1"]["agent_type"] == "codex"
    assert prompt_calls == [False]


@pytest.mark.asyncio
async def test_spawn_workers_returns_launch_blocked_hint(tmp_path, monkeypatch):
    """spawn_workers should surface launch blocker hints instead of iTerm advice."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    backend = FakeBackend()
    backend.raise_on_start = AgentLaunchBlocked(
        LaunchBlocker(
            slug="mcp_trust_confirmation",
            summary="Claude launch is blocked on the project MCP trust prompt.",
            hint="Open the worker pane and accept the .mcp.json server prompt once.",
        )
    )

    result = await _run_spawn_workers_tool(
        tmp_path,
        monkeypatch,
        backend,
        [{"project_path": str(repo_path), "name": "Worker1"}],
    )

    assert result["error"] == "Claude launch is blocked on the project MCP trust prompt."
    assert ".mcp.json server prompt" in result["hint"]


@pytest.mark.asyncio
async def test_spawn_workers_passes_auto_accept_startup_prompts(tmp_path, monkeypatch):
    """spawn_workers should pass terminal auto-accept config to the backend."""
    config = default_config()
    config.defaults = DefaultsConfig(use_worktree=False, layout="new")
    config.terminal.auto_accept_startup_prompts = True
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda agent_type: f"cli:{agent_type}")
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "get_coordinator_guidance",
        lambda *args, **kwargs: {"summary": "ok"},
    )

    async def fake_await_marker_in_jsonl(*args, **kwargs):
        return None

    async def fake_await_codex_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(session_state, "await_codex_marker_in_jsonl", fake_await_codex_marker_in_jsonl)
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
    await tool.run({
        "workers": [{"project_path": str(repo_path), "name": "Worker1"}],
    }, context=ctx)

    assert backend.started[0]["auto_accept_startup_prompts"] is True


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

    async def fake_await_codex_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(
        session_state,
        "await_codex_marker_in_jsonl",
        fake_await_codex_marker_in_jsonl,
    )
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
    assert backend.started[0]["env"] is None
    assert result["sessions"]["Worker1"]["agent_type"] == "claude"
    assert prompt_calls == [True]


@pytest.mark.asyncio
async def test_spawn_workers_merges_codex_ci_with_worktree_tracker_env(tmp_path, monkeypatch):
    """Codex workers should include CI=1 alongside worktree tracker env vars."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="codex",
        skip_permissions=False,
        use_worktree=False,
        layout="new",
    )
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda *_: "cli:codex")
    monkeypatch.setattr(
        spawn_workers_module,
        "get_worktree_tracker_dir",
        lambda *_: ("MANIPLE_WORKTREE_TRACKER_DIR", "/tmp/tracker"),
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "get_coordinator_guidance",
        lambda *args, **kwargs: {"summary": "ok"},
    )

    async def fake_await_marker_in_jsonl(*args, **kwargs):
        return None

    async def fake_await_codex_marker_in_jsonl(*args, **kwargs):
        return None

    monkeypatch.setattr(session_state, "await_marker_in_jsonl", fake_await_marker_in_jsonl)
    monkeypatch.setattr(
        session_state,
        "await_codex_marker_in_jsonl",
        fake_await_codex_marker_in_jsonl,
    )
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
    await tool.run({
        "workers": [{"project_path": str(repo_path), "name": "Worker1"}],
    }, context=ctx)

    assert backend.started[0]["env"] == {
        "MANIPLE_WORKTREE_TRACKER_DIR": "/tmp/tracker",
        "CI": "1",
    }


@pytest.mark.asyncio
async def test_spawn_workers_sets_badge_metadata(tmp_path, monkeypatch):
    """spawn_workers should forward badge metadata to sessions."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="claude",
        skip_permissions=False,
        use_worktree=False,
        layout="new",
    )
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda *_: "cli:claude")
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
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
        "workers": [{
            "project_path": str(repo_path),
            "name": "Worker1",
            "badge": "Preferred badge",
        }],
    }, context=ctx)

    session = result["sessions"]["Worker1"]
    assert session["coordinator_badge"] == "Preferred badge"
    assert backend.create_calls[0]["coordinator_badge"] == "Preferred badge"


@pytest.mark.asyncio
async def test_spawn_workers_uses_named_provider_preset(tmp_path, monkeypatch):
    """Named providers should supply per-worker command and env overrides."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="claude",
        skip_permissions=False,
        use_worktree=False,
        layout="new",
    )
    config.providers = {
        "local": ProviderConfig(
            command="/usr/local/bin/claude-local",
            env={"CLAUDE_PROVIDER": "local", "ANTHROPIC_BASE_URL": "http://provider"},
        )
    }
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda *_: "cli:claude")
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
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
    await tool.run({
        "workers": [{
            "project_path": str(repo_path),
            "name": "Worker1",
            "provider": "local",
        }],
    }, context=ctx)

    assert backend.started[0]["env"] == {
        "CLAUDE_PROVIDER": "local",
        "ANTHROPIC_BASE_URL": "http://provider",
    }
    assert backend.started[0]["command_override"] == "/usr/local/bin/claude-local"


@pytest.mark.asyncio
async def test_spawn_workers_uses_default_provider_when_not_specified(tmp_path, monkeypatch):
    """defaults.provider should apply when a worker omits provider/command/env."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="claude",
        skip_permissions=False,
        use_worktree=False,
        layout="new",
        provider="local",
    )
    config.providers = {
        "local": ProviderConfig(
            command="/usr/local/bin/claude-local",
            env={"CLAUDE_PROVIDER": "local"},
        )
    }
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda *_: "cli:claude")
    monkeypatch.setattr(spawn_workers_module, "get_worktree_tracker_dir", lambda *_: None)
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
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
    await tool.run({
        "workers": [{
            "project_path": str(repo_path),
            "name": "Worker1",
        }],
    }, context=ctx)

    assert backend.started[0]["env"] == {"CLAUDE_PROVIDER": "local"}
    assert backend.started[0]["command_override"] == "/usr/local/bin/claude-local"


@pytest.mark.asyncio
async def test_spawn_workers_uses_direct_command_and_env_override(tmp_path, monkeypatch):
    """Workers should support direct command/env overrides without providers."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="claude",
        skip_permissions=False,
        use_worktree=False,
        layout="new",
    )
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)
    monkeypatch.setattr(spawn_workers_module, "get_cli_backend", lambda *_: "cli:claude")
    monkeypatch.setattr(
        spawn_workers_module,
        "get_worktree_tracker_dir",
        lambda *_: ("MANIPLE_WORKTREE_TRACKER_DIR", "/tmp/tracker"),
    )
    monkeypatch.setattr(
        spawn_workers_module,
        "generate_worker_prompt",
        lambda *args, **kwargs: "PROMPT",
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
    await tool.run({
        "workers": [{
            "project_path": str(repo_path),
            "name": "Worker1",
            "command": "/usr/local/bin/claude-ckimi",
            "env": {"CLAUDE_PROVIDER": "ckimi"},
        }],
    }, context=ctx)

    assert backend.started[0]["env"] == {
        "MANIPLE_WORKTREE_TRACKER_DIR": "/tmp/tracker",
        "CLAUDE_PROVIDER": "ckimi",
    }
    assert backend.started[0]["command_override"] == "/usr/local/bin/claude-ckimi"


@pytest.mark.asyncio
async def test_spawn_workers_rejects_provider_and_command_mix(tmp_path, monkeypatch):
    """provider cannot be combined with direct command/env overrides."""
    config = default_config()
    config.defaults = DefaultsConfig(
        agent_type="claude",
        skip_permissions=False,
        use_worktree=False,
        layout="new",
    )
    config.providers = {
        "local": ProviderConfig(command="/bin/claude-local")
    }
    monkeypatch.setattr(spawn_workers_module, "load_config", lambda: config)

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
        "workers": [{
            "project_path": str(repo_path),
            "provider": "local",
            "command": "/bin/other",
        }],
    }, context=ctx)

    assert "error" in result
    assert "cannot combine 'provider' with 'command' or 'env'" in result["error"]
