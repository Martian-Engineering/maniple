"""Tests for config module."""

import json
import pytest
from pathlib import Path

from claude_team_mcp.config import (
    CONFIG_VERSION,
    ClaudeTeamConfig,
    CommandsConfig,
    ConfigError,
    DefaultsConfig,
    EventsConfig,
    IssueTrackerConfig,
    TerminalConfig,
    default_config,
    load_config,
    save_config,
)


class TestDefaultConfig:
    """Tests for default_config function."""

    def test_returns_claude_team_config(self):
        """default_config returns a ClaudeTeamConfig instance."""
        config = default_config()
        assert isinstance(config, ClaudeTeamConfig)

    def test_default_version(self):
        """Default config has current version."""
        config = default_config()
        assert config.version == CONFIG_VERSION

    def test_default_commands(self):
        """Default commands are None."""
        config = default_config()
        assert config.commands.claude is None
        assert config.commands.codex is None

    def test_default_defaults(self):
        """Default spawn_workers defaults."""
        config = default_config()
        assert config.defaults.agent_type == "claude"
        assert config.defaults.skip_permissions is False
        assert config.defaults.use_worktree is True
        assert config.defaults.layout == "auto"

    def test_default_terminal(self):
        """Default terminal backend is None (auto-detect)."""
        config = default_config()
        assert config.terminal.backend is None

    def test_default_events(self):
        """Default events config values."""
        config = default_config()
        assert config.events.max_size_mb == 1
        assert config.events.recent_hours == 24

    def test_default_issue_tracker(self):
        """Default issue tracker override is None."""
        config = default_config()
        assert config.issue_tracker.override is None


class TestSaveConfig:
    """Tests for save_config function."""

    def test_creates_parent_directory(self, tmp_path: Path):
        """save_config creates parent directories if needed."""
        nested_path = tmp_path / "a" / "b" / "config.json"
        config = default_config()
        save_config(config, nested_path)
        assert nested_path.exists()

    def test_writes_valid_json(self, tmp_path: Path):
        """Saved config is valid JSON."""
        config_path = tmp_path / "config.json"
        config = default_config()
        save_config(config, config_path)
        data = json.loads(config_path.read_text())
        assert isinstance(data, dict)

    def test_returns_path_written(self, tmp_path: Path):
        """save_config returns the path that was written."""
        config_path = tmp_path / "config.json"
        config = default_config()
        result = save_config(config, config_path)
        assert result == config_path

    def test_saves_all_fields(self, tmp_path: Path):
        """All config fields are persisted."""
        config_path = tmp_path / "config.json"
        config = ClaudeTeamConfig(
            version=1,
            commands=CommandsConfig(claude="/custom/claude", codex="/custom/codex"),
            defaults=DefaultsConfig(
                agent_type="codex",
                skip_permissions=True,
                use_worktree=False,
                layout="new",
            ),
            terminal=TerminalConfig(backend="tmux"),
            events=EventsConfig(max_size_mb=5, recent_hours=48),
            issue_tracker=IssueTrackerConfig(override="beads"),
        )
        save_config(config, config_path)
        data = json.loads(config_path.read_text())
        assert data["version"] == 1
        assert data["commands"]["claude"] == "/custom/claude"
        assert data["commands"]["codex"] == "/custom/codex"
        assert data["defaults"]["agent_type"] == "codex"
        assert data["defaults"]["skip_permissions"] is True
        assert data["defaults"]["use_worktree"] is False
        assert data["defaults"]["layout"] == "new"
        assert data["terminal"]["backend"] == "tmux"
        assert data["events"]["max_size_mb"] == 5
        assert data["events"]["recent_hours"] == 48
        assert data["issue_tracker"]["override"] == "beads"

    def test_json_is_formatted(self, tmp_path: Path):
        """Saved JSON is indented for readability."""
        config_path = tmp_path / "config.json"
        config = default_config()
        save_config(config, config_path)
        content = config_path.read_text()
        # Indented JSON has newlines and spaces
        assert "\n" in content
        assert "  " in content

    def test_file_ends_with_newline(self, tmp_path: Path):
        """Saved file ends with newline."""
        config_path = tmp_path / "config.json"
        config = default_config()
        save_config(config, config_path)
        content = config_path.read_text()
        assert content.endswith("\n")


class TestLoadConfig:
    """Tests for load_config function."""

    def test_creates_default_when_missing(self, tmp_path: Path):
        """load_config returns defaults without writing when file doesn't exist."""
        config_path = tmp_path / "config.json"
        assert not config_path.exists()
        config = load_config(config_path)
        assert not config_path.exists()
        assert isinstance(config, ClaudeTeamConfig)

    def test_loads_existing_config(self, tmp_path: Path):
        """load_config reads existing config file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"claude": "/my/claude"},
            "defaults": {"agent_type": "codex"},
            "terminal": {"backend": "iterm"},
            "events": {"max_size_mb": 10},
            "issue_tracker": {"override": "pebbles"},
        }))
        config = load_config(config_path)
        assert config.commands.claude == "/my/claude"
        assert config.defaults.agent_type == "codex"
        assert config.terminal.backend == "iterm"
        assert config.events.max_size_mb == 10
        assert config.issue_tracker.override == "pebbles"

    def test_partial_config_uses_defaults(self, tmp_path: Path):
        """Missing sections use default values."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"version": 1}))
        config = load_config(config_path)
        # All other fields should have defaults
        assert config.commands.claude is None
        assert config.defaults.agent_type == "claude"
        assert config.terminal.backend is None
        assert config.events.max_size_mb == 1
        assert config.issue_tracker.override is None

    def test_empty_sections_use_defaults(self, tmp_path: Path):
        """Empty section objects use field defaults."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {},
            "defaults": {},
            "terminal": {},
            "events": {},
            "issue_tracker": {},
        }))
        config = load_config(config_path)
        assert config.defaults.agent_type == "claude"
        assert config.defaults.skip_permissions is False

    def test_roundtrip_preserves_values(self, tmp_path: Path):
        """Saving and loading preserves all config values."""
        config_path = tmp_path / "config.json"
        original = ClaudeTeamConfig(
            version=1,
            commands=CommandsConfig(claude="/bin/claude", codex="/bin/codex"),
            defaults=DefaultsConfig(
                agent_type="codex",
                skip_permissions=True,
                use_worktree=False,
                layout="new",
            ),
            terminal=TerminalConfig(backend="tmux"),
            events=EventsConfig(max_size_mb=2, recent_hours=12),
            issue_tracker=IssueTrackerConfig(override="beads"),
        )
        save_config(original, config_path)
        loaded = load_config(config_path)
        assert loaded.version == original.version
        assert loaded.commands.claude == original.commands.claude
        assert loaded.commands.codex == original.commands.codex
        assert loaded.defaults.agent_type == original.defaults.agent_type
        assert loaded.defaults.skip_permissions == original.defaults.skip_permissions
        assert loaded.defaults.use_worktree == original.defaults.use_worktree
        assert loaded.defaults.layout == original.defaults.layout
        assert loaded.terminal.backend == original.terminal.backend
        assert loaded.events.max_size_mb == original.events.max_size_mb
        assert loaded.events.recent_hours == original.events.recent_hours
        assert loaded.issue_tracker.override == original.issue_tracker.override


class TestJsonValidationErrors:
    """Tests for JSON validation error handling."""

    def test_invalid_json_raises_config_error(self, tmp_path: Path):
        """Invalid JSON content raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(config_path)

    def test_non_object_json_raises_config_error(self, tmp_path: Path):
        """Non-object JSON raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text('"just a string"')
        with pytest.raises(ConfigError, match="must contain a JSON object"):
            load_config(config_path)

    def test_array_json_raises_config_error(self, tmp_path: Path):
        """JSON array raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text("[1, 2, 3]")
        with pytest.raises(ConfigError, match="must contain a JSON object"):
            load_config(config_path)

    def test_unknown_top_level_key_raises_error(self, tmp_path: Path):
        """Unknown keys in config raise ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "unknown_key": "value",
        }))
        with pytest.raises(ConfigError, match="Unknown keys in config"):
            load_config(config_path)

    def test_unknown_commands_key_raises_error(self, tmp_path: Path):
        """Unknown keys in commands section raise ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"invalid": "value"},
        }))
        with pytest.raises(ConfigError, match="Unknown keys in commands"):
            load_config(config_path)

    def test_unknown_defaults_key_raises_error(self, tmp_path: Path):
        """Unknown keys in defaults section raise ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"bad_key": True},
        }))
        with pytest.raises(ConfigError, match="Unknown keys in defaults"):
            load_config(config_path)

    def test_unknown_terminal_key_raises_error(self, tmp_path: Path):
        """Unknown keys in terminal section raise ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "terminal": {"unknown": "value"},
        }))
        with pytest.raises(ConfigError, match="Unknown keys in terminal"):
            load_config(config_path)

    def test_unknown_events_key_raises_error(self, tmp_path: Path):
        """Unknown keys in events section raise ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"bad": 123},
        }))
        with pytest.raises(ConfigError, match="Unknown keys in events"):
            load_config(config_path)

    def test_unknown_issue_tracker_key_raises_error(self, tmp_path: Path):
        """Unknown keys in issue_tracker section raise ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "issue_tracker": {"invalid": "pebbles"},
        }))
        with pytest.raises(ConfigError, match="Unknown keys in issue_tracker"):
            load_config(config_path)

    def test_section_not_object_raises_error(self, tmp_path: Path):
        """Section that is not an object raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": "not an object",
        }))
        with pytest.raises(ConfigError, match="commands must be a JSON object"):
            load_config(config_path)

    def test_section_array_raises_error(self, tmp_path: Path):
        """Section that is an array raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": [1, 2, 3],
        }))
        with pytest.raises(ConfigError, match="defaults must be a JSON object"):
            load_config(config_path)


class TestVersionValidation:
    """Tests for config version validation."""

    def test_missing_version_uses_current(self, tmp_path: Path):
        """Missing version field defaults to current version."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))
        config = load_config(config_path)
        assert config.version == CONFIG_VERSION

    def test_current_version_accepted(self, tmp_path: Path):
        """Current version is accepted."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"version": CONFIG_VERSION}))
        config = load_config(config_path)
        assert config.version == CONFIG_VERSION

    def test_wrong_version_raises_error(self, tmp_path: Path):
        """Unsupported version raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"version": 999}))
        with pytest.raises(ConfigError, match="Unsupported config version 999"):
            load_config(config_path)

    def test_version_not_integer_raises_error(self, tmp_path: Path):
        """Non-integer version raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"version": "1"}))
        with pytest.raises(ConfigError, match="version must be an integer"):
            load_config(config_path)

    def test_future_version_raises_error(self, tmp_path: Path):
        """Future version raises ConfigError (for migration testing)."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"version": CONFIG_VERSION + 1}))
        with pytest.raises(ConfigError, match="Unsupported config version"):
            load_config(config_path)


class TestFieldTypeValidation:
    """Tests for field type validation."""

    def test_commands_claude_must_be_string(self, tmp_path: Path):
        """commands.claude must be a string."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"claude": 123},
        }))
        with pytest.raises(ConfigError, match="commands.claude must be a string"):
            load_config(config_path)

    def test_commands_codex_must_be_string(self, tmp_path: Path):
        """commands.codex must be a string."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"codex": True},
        }))
        with pytest.raises(ConfigError, match="commands.codex must be a string"):
            load_config(config_path)

    def test_commands_empty_string_raises_error(self, tmp_path: Path):
        """Empty command string raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"claude": ""},
        }))
        with pytest.raises(ConfigError, match="commands.claude cannot be empty"):
            load_config(config_path)

    def test_commands_whitespace_string_raises_error(self, tmp_path: Path):
        """Whitespace-only command string raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "commands": {"claude": "   "},
        }))
        with pytest.raises(ConfigError, match="commands.claude cannot be empty"):
            load_config(config_path)

    def test_defaults_agent_type_invalid_value(self, tmp_path: Path):
        """Invalid agent_type raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"agent_type": "invalid"},
        }))
        with pytest.raises(ConfigError, match="defaults.agent_type must be one of"):
            load_config(config_path)

    def test_defaults_agent_type_not_string(self, tmp_path: Path):
        """Non-string agent_type raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"agent_type": 1},
        }))
        with pytest.raises(ConfigError, match="defaults.agent_type must be a string"):
            load_config(config_path)

    def test_defaults_skip_permissions_not_bool(self, tmp_path: Path):
        """Non-boolean skip_permissions raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"skip_permissions": "yes"},
        }))
        with pytest.raises(ConfigError, match="defaults.skip_permissions must be a boolean"):
            load_config(config_path)

    def test_defaults_use_worktree_not_bool(self, tmp_path: Path):
        """Non-boolean use_worktree raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"use_worktree": 1},
        }))
        with pytest.raises(ConfigError, match="defaults.use_worktree must be a boolean"):
            load_config(config_path)

    def test_defaults_layout_invalid_value(self, tmp_path: Path):
        """Invalid layout raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"layout": "grid"},
        }))
        with pytest.raises(ConfigError, match="defaults.layout must be one of"):
            load_config(config_path)

    def test_terminal_backend_invalid_value(self, tmp_path: Path):
        """Invalid terminal backend raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "terminal": {"backend": "kitty"},
        }))
        with pytest.raises(ConfigError, match="terminal.backend must be one of"):
            load_config(config_path)

    def test_events_max_size_mb_not_int(self, tmp_path: Path):
        """Non-integer max_size_mb raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"max_size_mb": "5"},
        }))
        with pytest.raises(ConfigError, match="events.max_size_mb must be an integer"):
            load_config(config_path)

    def test_events_max_size_mb_zero_raises_error(self, tmp_path: Path):
        """Zero max_size_mb raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"max_size_mb": 0},
        }))
        with pytest.raises(ConfigError, match="events.max_size_mb must be at least 1"):
            load_config(config_path)

    def test_events_max_size_mb_negative_raises_error(self, tmp_path: Path):
        """Negative max_size_mb raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"max_size_mb": -1},
        }))
        with pytest.raises(ConfigError, match="events.max_size_mb must be at least 1"):
            load_config(config_path)

    def test_events_recent_hours_not_int(self, tmp_path: Path):
        """Non-integer recent_hours raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"recent_hours": 24.5},
        }))
        with pytest.raises(ConfigError, match="events.recent_hours must be an integer"):
            load_config(config_path)

    def test_events_recent_hours_zero_allowed(self, tmp_path: Path):
        """Zero recent_hours is allowed."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"recent_hours": 0},
        }))
        config = load_config(config_path)
        assert config.events.recent_hours == 0

    def test_events_recent_hours_negative_raises_error(self, tmp_path: Path):
        """Negative recent_hours raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"recent_hours": -1},
        }))
        with pytest.raises(ConfigError, match="events.recent_hours must be at least 0"):
            load_config(config_path)

    def test_events_bool_not_accepted_as_int(self, tmp_path: Path):
        """Boolean is not accepted for integer field."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "events": {"max_size_mb": True},
        }))
        with pytest.raises(ConfigError, match="events.max_size_mb must be an integer"):
            load_config(config_path)

    def test_issue_tracker_override_invalid_value(self, tmp_path: Path):
        """Invalid issue_tracker.override raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "issue_tracker": {"override": "jira"},
        }))
        with pytest.raises(ConfigError, match="issue_tracker.override must be one of"):
            load_config(config_path)


class TestValidLiteralValues:
    """Tests for valid literal string values."""

    def test_agent_type_claude(self, tmp_path: Path):
        """agent_type 'claude' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"agent_type": "claude"},
        }))
        config = load_config(config_path)
        assert config.defaults.agent_type == "claude"

    def test_agent_type_codex(self, tmp_path: Path):
        """agent_type 'codex' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"agent_type": "codex"},
        }))
        config = load_config(config_path)
        assert config.defaults.agent_type == "codex"

    def test_layout_auto(self, tmp_path: Path):
        """layout 'auto' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"layout": "auto"},
        }))
        config = load_config(config_path)
        assert config.defaults.layout == "auto"

    def test_layout_new(self, tmp_path: Path):
        """layout 'new' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "defaults": {"layout": "new"},
        }))
        config = load_config(config_path)
        assert config.defaults.layout == "new"

    def test_terminal_backend_iterm(self, tmp_path: Path):
        """terminal.backend 'iterm' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "terminal": {"backend": "iterm"},
        }))
        config = load_config(config_path)
        assert config.terminal.backend == "iterm"

    def test_terminal_backend_tmux(self, tmp_path: Path):
        """terminal.backend 'tmux' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "terminal": {"backend": "tmux"},
        }))
        config = load_config(config_path)
        assert config.terminal.backend == "tmux"

    def test_issue_tracker_override_beads(self, tmp_path: Path):
        """issue_tracker.override 'beads' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "issue_tracker": {"override": "beads"},
        }))
        config = load_config(config_path)
        assert config.issue_tracker.override == "beads"

    def test_issue_tracker_override_pebbles(self, tmp_path: Path):
        """issue_tracker.override 'pebbles' is valid."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "version": 1,
            "issue_tracker": {"override": "pebbles"},
        }))
        config = load_config(config_path)
        assert config.issue_tracker.override == "pebbles"


class TestIOErrors:
    """Tests for IO error handling."""

    def test_unreadable_file_raises_config_error(self, tmp_path: Path):
        """Unreadable config file raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.write_text("{}")
        config_path.chmod(0o000)
        try:
            with pytest.raises(ConfigError, match="Unable to read config file"):
                load_config(config_path)
        finally:
            # Restore permissions for cleanup
            config_path.chmod(0o644)

    def test_directory_instead_of_file_raises_error(self, tmp_path: Path):
        """Directory path instead of file raises ConfigError."""
        config_path = tmp_path / "config.json"
        config_path.mkdir()
        with pytest.raises(ConfigError, match="Unable to read config file"):
            load_config(config_path)


class TestDataclasses:
    """Tests for dataclass behavior."""

    def test_commands_config_defaults(self):
        """CommandsConfig has correct defaults."""
        config = CommandsConfig()
        assert config.claude is None
        assert config.codex is None

    def test_defaults_config_defaults(self):
        """DefaultsConfig has correct defaults."""
        config = DefaultsConfig()
        assert config.agent_type == "claude"
        assert config.skip_permissions is False
        assert config.use_worktree is True
        assert config.layout == "auto"

    def test_terminal_config_defaults(self):
        """TerminalConfig has correct defaults."""
        config = TerminalConfig()
        assert config.backend is None

    def test_events_config_defaults(self):
        """EventsConfig has correct defaults."""
        config = EventsConfig()
        assert config.max_size_mb == 1
        assert config.recent_hours == 24

    def test_issue_tracker_config_defaults(self):
        """IssueTrackerConfig has correct defaults."""
        config = IssueTrackerConfig()
        assert config.override is None

    def test_claude_team_config_defaults(self):
        """ClaudeTeamConfig has correct nested defaults."""
        config = ClaudeTeamConfig()
        assert config.version == CONFIG_VERSION
        assert isinstance(config.commands, CommandsConfig)
        assert isinstance(config.defaults, DefaultsConfig)
        assert isinstance(config.terminal, TerminalConfig)
        assert isinstance(config.events, EventsConfig)
        assert isinstance(config.issue_tracker, IssueTrackerConfig)
