"""Tests for config CLI helpers."""

import json
from pathlib import Path

import pytest

from claude_team_mcp import config as config_module
from claude_team_mcp.config import ConfigError, load_config
from claude_team_mcp.config_cli import (
    get_config_value,
    init_config,
    load_effective_config_data,
    render_config_json,
    set_config_value,
)


@pytest.fixture(autouse=True)
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config path to a temp location for deterministic tests."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    return path


class TestConfigInit:
    """Tests for config init helper."""

    def test_init_creates_default(self, config_path: Path):
        """init_config writes the default config file."""
        result = init_config()
        assert result == config_path
        assert config_path.exists()

    def test_init_errors_when_exists(self, config_path: Path):
        """init_config errors without --force if file exists."""
        config_path.write_text("{}")
        with pytest.raises(ConfigError, match="already exists"):
            init_config()


class TestConfigShow:
    """Tests for config show helper."""

    def test_show_merges_env_overrides(self, config_path: Path):
        """render_config_json applies env overrides on top of config."""
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"claude": "/from/config"},
            "events": {"max_size_mb": 2},
        }))
        env = {
            "CLAUDE_TEAM_COMMAND": "from-env",
            "CLAUDE_TEAM_EVENTS_MAX_SIZE_MB": "5",
        }
        data = load_effective_config_data(env=env)
        assert data["commands"]["claude"] == "from-env"
        assert data["events"]["max_size_mb"] == 5

    def test_show_renders_json(self, config_path: Path):
        """render_config_json returns formatted JSON."""
        config_path.write_text(json.dumps({"version": 1}))
        payload = render_config_json()
        parsed = json.loads(payload)
        assert parsed["version"] == 1


class TestConfigGet:
    """Tests for config get helper."""

    def test_get_reads_dotted_value(self, config_path: Path):
        """get_config_value returns values by dotted path."""
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"layout": "new"},
        }))
        assert get_config_value("defaults.layout") == "new"

    def test_get_reads_env_override(self, config_path: Path):
        """get_config_value returns env-overridden values."""
        config_path.write_text(json.dumps({"version": 1}))
        env = {"CLAUDE_TEAM_TERMINAL_BACKEND": "tmux"}
        assert get_config_value("terminal.backend", env=env) == "tmux"


class TestConfigSet:
    """Tests for config set helper."""

    def test_set_creates_file_and_saves(self, config_path: Path):
        """set_config_value creates file and persists updates."""
        set_config_value("defaults.skip_permissions", "true")
        config = load_config()
        assert config.defaults.skip_permissions is True

    def test_set_validates_values(self, config_path: Path):
        """set_config_value validates against the schema."""
        with pytest.raises(ConfigError, match="defaults.layout must be one of"):
            set_config_value("defaults.layout", "grid")

    def test_set_rejects_unknown_key(self, config_path: Path):
        """set_config_value rejects unknown keys."""
        with pytest.raises(ConfigError, match="Unknown config key"):
            set_config_value("defaults.unknown", "true")
