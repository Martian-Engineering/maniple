"""Tests for iterm_utils module."""

import os
from unittest.mock import patch

import pytest

from maniple_mcp.iterm_utils import build_stop_hook_settings_file, wait_for_agent_ready
from maniple_mcp.launch_blockers import AgentLaunchBlocked


class _FakeClaudeCLI:
    engine_id = "claude"

    def ready_patterns(self):
        return [">", "tokens"]


@pytest.mark.asyncio
async def test_wait_for_agent_ready_raises_on_mcp_trust_prompt(monkeypatch):
    async def fake_read_screen_text(_session):
        return (
            "New MCP server found in .mcp.json\n"
            "1. Use this and all future MCP servers in this project\n"
        )

    monkeypatch.setattr("maniple_mcp.iterm_utils.read_screen_text", fake_read_screen_text)

    with pytest.raises(AgentLaunchBlocked) as excinfo:
        await wait_for_agent_ready(object(), _FakeClaudeCLI(), timeout_seconds=1.0)

    assert "MCP trust prompt" in str(excinfo.value)


@pytest.mark.asyncio
async def test_wait_for_agent_ready_raises_on_bypass_permissions_prompt(monkeypatch):
    async def fake_read_screen_text(_session):
        return (
            "WARNING: Claude Code running in Bypass Permissions mode\n"
            "2. Yes, I accept\n"
        )

    monkeypatch.setattr("maniple_mcp.iterm_utils.read_screen_text", fake_read_screen_text)

    with pytest.raises(AgentLaunchBlocked) as excinfo:
        await wait_for_agent_ready(object(), _FakeClaudeCLI(), timeout_seconds=1.0)

    assert "Bypass Permissions confirmation" in str(excinfo.value)


@pytest.mark.asyncio
async def test_wait_for_agent_ready_auto_accepts_bypass_permissions(monkeypatch):
    responses = iter([
        "WARNING: Claude Code running in Bypass Permissions mode\n2. Yes, I accept\n",
        "> ",
        "> ",
        "> ",
    ])
    sent = []

    async def fake_read_screen_text(_session):
        return next(responses)

    async def fake_send_text(_session, text):
        sent.append(("text", text))

    async def fake_send_key(_session, key):
        sent.append(("key", key))

    monkeypatch.setattr("maniple_mcp.iterm_utils.read_screen_text", fake_read_screen_text)
    monkeypatch.setattr("maniple_mcp.iterm_utils.send_text", fake_send_text)
    monkeypatch.setattr("maniple_mcp.iterm_utils.send_key", fake_send_key)

    ready = await wait_for_agent_ready(
        object(),
        _FakeClaudeCLI(),
        timeout_seconds=2.0,
        auto_accept_startup_prompts=True,
    )

    assert ready is True
    assert sent == [("text", "2"), ("key", "enter")]


class TestClaudeCommandBuilding:
    """Tests for Claude command building logic in start_claude_in_session.

    These tests verify the --settings flag behavior based on MANIPLE_COMMAND.
    The actual start_claude_in_session function is async and requires iTerm2,
    so we test the command building logic by examining the key conditions.
    """

    def test_default_claude_command_gets_settings(self):
        """Default 'claude' command should get --settings flag for idle detection."""
        # Simulate the logic from start_claude_in_session
        with patch.dict(os.environ, {}, clear=False):
            # Remove MANIPLE_COMMAND if present
            os.environ.pop("MANIPLE_COMMAND", None)

            claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")
            is_default_claude_command = claude_cmd == "claude"

            assert claude_cmd == "claude"
            assert is_default_claude_command is True

            # With a stop_hook_marker_id, --settings should be added
            stop_hook_marker_id = "test-marker-123"
            if stop_hook_marker_id and is_default_claude_command:
                settings_file = build_stop_hook_settings_file(stop_hook_marker_id)
                claude_cmd += f" --settings {settings_file}"

            assert "--settings" in claude_cmd
            assert "test-marker-123" in settings_file

    def test_custom_command_skips_settings(self):
        """Custom commands like 'happy' should NOT get --settings flag.

        Custom commands have their own session tracking mechanisms.
        Adding --settings conflicts with them (e.g., Happy's SessionStart hook).
        """
        with patch.dict(os.environ, {"MANIPLE_COMMAND": "happy"}):
            claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")
            is_default_claude_command = claude_cmd == "claude"

            assert claude_cmd == "happy"
            assert is_default_claude_command is False

            # With a stop_hook_marker_id, --settings should NOT be added
            stop_hook_marker_id = "test-marker-123"
            if stop_hook_marker_id and is_default_claude_command:
                settings_file = build_stop_hook_settings_file(stop_hook_marker_id)
                claude_cmd += f" --settings {settings_file}"

            assert "--settings" not in claude_cmd

    def test_custom_command_with_path_skips_settings(self):
        """Custom commands specified as paths should also skip --settings."""
        with patch.dict(os.environ, {"MANIPLE_COMMAND": "/usr/local/bin/happy"}):
            claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")
            is_default_claude_command = claude_cmd == "claude"

            assert claude_cmd == "/usr/local/bin/happy"
            assert is_default_claude_command is False

            stop_hook_marker_id = "test-marker-123"
            if stop_hook_marker_id and is_default_claude_command:
                settings_file = build_stop_hook_settings_file(stop_hook_marker_id)
                claude_cmd += f" --settings {settings_file}"

            assert "--settings" not in claude_cmd

    def test_bypass_permissions_mode_still_added(self):
        """Bypass permission mode should be added regardless of command."""
        # Test with default claude
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MANIPLE_COMMAND", None)
            claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")

            dangerously_skip_permissions = True
            if dangerously_skip_permissions:
                claude_cmd += " --permission-mode bypassPermissions"

            assert "--permission-mode bypassPermissions" in claude_cmd

        # Test with custom command
        with patch.dict(os.environ, {"MANIPLE_COMMAND": "happy"}):
            claude_cmd = os.environ.get("MANIPLE_COMMAND", "claude")

            dangerously_skip_permissions = True
            if dangerously_skip_permissions:
                claude_cmd += " --permission-mode bypassPermissions"

            assert "--permission-mode bypassPermissions" in claude_cmd
            assert claude_cmd == "happy --permission-mode bypassPermissions"


class TestBuildStopHookSettingsFile:
    """Tests for the stop hook settings file builder."""

    def test_creates_valid_settings_file(self):
        """Settings file should contain Stop hook with marker."""
        import json
        from pathlib import Path

        marker_id = "test-abc123"
        settings_path = build_stop_hook_settings_file(marker_id)

        # Verify file exists and is valid JSON
        settings_file = Path(settings_path)
        assert settings_file.exists()

        content = json.loads(settings_file.read_text())
        assert "hooks" in content
        assert "Stop" in content["hooks"]

        # Verify marker is in the command
        stop_hooks = content["hooks"]["Stop"]
        assert len(stop_hooks) > 0
        command = stop_hooks[0]["hooks"][0]["command"]
        assert marker_id in command

    def test_settings_file_in_expected_location(self):
        """Settings file should be in ~/.claude/claude-team-settings/."""
        from pathlib import Path

        marker_id = "location-test-456"
        settings_path = build_stop_hook_settings_file(marker_id)

        expected_dir = Path.home() / ".claude" / "claude-team-settings"
        assert settings_path.startswith(str(expected_dir))
