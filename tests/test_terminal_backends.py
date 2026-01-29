"""Tests for terminal backend selection."""

from claude_team_mcp.config import ClaudeTeamConfig, TerminalConfig
from claude_team_mcp.terminal_backends import select_backend_id


def test_select_backend_id_env_overrides_config():
    """Environment variable should override config backend."""
    env = {"CLAUDE_TEAM_TERMINAL_BACKEND": "ITERM"}
    config = ClaudeTeamConfig(terminal=TerminalConfig(backend="tmux"))
    assert select_backend_id(env=env, config=config) == "iterm"


def test_select_backend_id_uses_config_when_env_missing():
    """Config backend should be used when env var is missing."""
    env = {}
    config = ClaudeTeamConfig(terminal=TerminalConfig(backend="tmux"))
    assert select_backend_id(env=env, config=config) == "tmux"


def test_select_backend_id_auto_detects_tmux():
    """Auto-detect should select tmux when TMUX env var is set."""
    env = {"TMUX": "1"}
    config = ClaudeTeamConfig(terminal=TerminalConfig(backend=None))
    assert select_backend_id(env=env, config=config) == "tmux"


def test_select_backend_id_defaults_to_iterm():
    """Auto-detect should default to iterm when no signal is present."""
    env = {}
    config = ClaudeTeamConfig(terminal=TerminalConfig(backend=None))
    assert select_backend_id(env=env, config=config) == "iterm"
