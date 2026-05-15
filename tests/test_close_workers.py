"""Tests for the close_workers tool."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

close_workers_module = importlib.import_module("maniple_mcp.tools.close_workers")


class FakeBackend:
    """Minimal backend for close_workers tests."""

    def __init__(self) -> None:
        self.sent_keys: list[tuple[str, str]] = []
        self.sent_texts: list[tuple[str, str]] = []
        self.closed: list[tuple[str, bool]] = []

    async def send_key(self, session, key: str) -> None:
        self.sent_keys.append((session.native_id, key))

    async def send_text(self, session, text: str) -> None:
        self.sent_texts.append((session.native_id, text))

    async def close_session(self, session, force: bool = False) -> None:
        self.closed.append((session.native_id, force))


async def _no_sleep(_: float) -> None:
    """Skip timing delays in tests."""


class FakeRegistry:
    """Minimal registry for close_workers tests."""

    def __init__(self, session) -> None:
        self.session = session
        self.removed: list[str] = []

    def resolve(self, session_id: str):
        if self.session and session_id == self.session.session_id:
            return self.session
        return None

    def remove(self, session_id: str):
        self.removed.append(session_id)
        if self.session and session_id == self.session.session_id:
            session = self.session
            self.session = None
            return session
        return None


def _make_session() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="worker-1",
        status=close_workers_module.SessionStatus.READY,
        agent_type="claude",
        terminal_session=SimpleNamespace(native_id="%1"),
        main_repo_path=Path("/repo"),
        worktree_path=Path("/repo/.worktrees/worker-branch"),
    )


def _build_tool(backend: FakeBackend, registry: FakeRegistry):
    app_ctx = SimpleNamespace(registry=registry, terminal_backend=backend)
    mcp = FastMCP("test")
    close_workers_module.register_tools(mcp)
    tool = mcp._tool_manager.get_tool("close_workers")
    assert tool is not None
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app_ctx))
    return tool, ctx


@pytest.mark.asyncio
async def test_close_workers_keeps_branch_by_default(monkeypatch):
    """close_workers should remove the worktree but keep the branch by default."""
    monkeypatch.setattr(close_workers_module.asyncio, "sleep", _no_sleep)

    removed: list[tuple[Path, Path]] = []
    deleted_branches: list[tuple[Path, str]] = []

    monkeypatch.setattr(
        close_workers_module,
        "get_worktree_branch",
        lambda repo_path, worktree_path: "worker-branch",
    )
    monkeypatch.setattr(
        close_workers_module,
        "remove_worktree",
        lambda repo_path, worktree_path: removed.append((repo_path, worktree_path)) or True,
    )
    monkeypatch.setattr(
        close_workers_module,
        "delete_worktree_branch",
        lambda repo_path, branch_name: deleted_branches.append((repo_path, branch_name)) or True,
    )

    backend = FakeBackend()
    registry = FakeRegistry(_make_session())

    tool, ctx = _build_tool(backend, registry)
    result = await tool.run({"session_ids": ["worker-1"]}, context=ctx)

    assert result["success_count"] == 1
    assert result["results"]["worker-1"]["worktree_cleaned"] is True
    assert result["results"]["worker-1"]["branch_deleted"] is False
    assert removed == [(Path("/repo"), Path("/repo/.worktrees/worker-branch"))]
    assert deleted_branches == []


@pytest.mark.asyncio
async def test_close_workers_can_delete_branch(monkeypatch):
    """close_workers should optionally delete the branch after removing the worktree."""
    monkeypatch.setattr(close_workers_module.asyncio, "sleep", _no_sleep)

    call_order: list[str] = []

    monkeypatch.setattr(
        close_workers_module,
        "get_worktree_branch",
        lambda repo_path, worktree_path: "worker-branch",
    )
    monkeypatch.setattr(
        close_workers_module,
        "remove_worktree",
        lambda repo_path, worktree_path: call_order.append("remove_worktree") or True,
    )
    monkeypatch.setattr(
        close_workers_module,
        "delete_worktree_branch",
        lambda repo_path, branch_name: call_order.append(f"delete_branch:{branch_name}") or True,
    )

    backend = FakeBackend()
    registry = FakeRegistry(_make_session())

    tool, ctx = _build_tool(backend, registry)
    result = await tool.run(
        {"session_ids": ["worker-1"], "delete_branch": True},
        context=ctx,
    )

    assert result["success_count"] == 1
    assert result["results"]["worker-1"]["worktree_cleaned"] is True
    assert result["results"]["worker-1"]["branch_deleted"] is True
    assert call_order == ["remove_worktree", "delete_branch:worker-branch"]


@pytest.mark.asyncio
async def test_close_workers_skips_branch_delete_when_worktree_cleanup_fails(monkeypatch):
    """Branch deletion should not run if worktree removal fails."""
    monkeypatch.setattr(close_workers_module.asyncio, "sleep", _no_sleep)

    deleted_branches: list[str] = []

    monkeypatch.setattr(
        close_workers_module,
        "get_worktree_branch",
        lambda repo_path, worktree_path: "worker-branch",
    )

    def fail_remove_worktree(repo_path, worktree_path):
        raise close_workers_module.WorktreeError("boom")

    monkeypatch.setattr(close_workers_module, "remove_worktree", fail_remove_worktree)
    monkeypatch.setattr(
        close_workers_module,
        "delete_worktree_branch",
        lambda repo_path, branch_name: deleted_branches.append(branch_name) or True,
    )

    backend = FakeBackend()
    registry = FakeRegistry(_make_session())

    tool, ctx = _build_tool(backend, registry)
    result = await tool.run(
        {"session_ids": ["worker-1"], "delete_branch": True},
        context=ctx,
    )

    assert result["success_count"] == 1
    assert result["results"]["worker-1"]["worktree_cleaned"] is False
    assert result["results"]["worker-1"]["branch_deleted"] is False
    assert deleted_branches == []
