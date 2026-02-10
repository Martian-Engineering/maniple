"""Tests for terminal backend selection."""

import pytest

import maniple_mcp.terminal_backends as terminal_backends
from maniple_mcp.config import ClaudeTeamConfig, ConfigError, TerminalConfig
from maniple_mcp.terminal_backends import select_backend_id


def test_select_backend_id_env_overrides_config():
    """Environment variable should override config backend."""
    env = {"MANIPLE_TERMINAL_BACKEND": "ITERM"}
    config = ClaudeTeamConfig(terminal=TerminalConfig(backend="tmux"))
    assert select_backend_id(env=env, config=config) == "iterm"

def test_select_backend_id_deprecated_env_overrides_config():
    """Deprecated CLAUDE_TEAM_TERMINAL_BACKEND should still override config."""
    env = {"CLAUDE_TEAM_TERMINAL_BACKEND": "TMUX"}
    config = ClaudeTeamConfig(terminal=TerminalConfig(backend="iterm"))
    assert select_backend_id(env=env, config=config) == "tmux"

def test_select_backend_id_env_precedence():
    """MANIPLE_TERMINAL_BACKEND should take precedence over CLAUDE_TEAM_TERMINAL_BACKEND."""
    env = {"MANIPLE_TERMINAL_BACKEND": "iterm", "CLAUDE_TEAM_TERMINAL_BACKEND": "tmux"}
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


def test_select_backend_id_invalid_config_falls_back(monkeypatch, caplog):
    """Invalid config should fall back to auto-detect defaults."""
    env = {}

    def raise_config_error():
        raise ConfigError("invalid config")

    monkeypatch.setattr(terminal_backends, "load_config", raise_config_error)

    with caplog.at_level("WARNING"):
        assert select_backend_id(env=env, config=None) == "iterm"

    assert "Invalid config file; ignoring terminal backend override" in caplog.text
