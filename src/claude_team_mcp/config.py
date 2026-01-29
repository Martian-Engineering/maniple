"""
Configuration loading for Claude Team MCP.

Defines dataclasses for the config schema and utilities for loading
and validating JSON config files.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

CONFIG_VERSION = 1
CONFIG_DIR = Path.home() / ".claude-team"
CONFIG_PATH = CONFIG_DIR / "config.json"

AgentType = Literal["claude", "codex"]
LayoutMode = Literal["auto", "new"]
TerminalBackend = Literal["iterm", "tmux"]
IssueTrackerName = Literal["beads", "pebbles"]


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""


@dataclass
class CommandsConfig:
    """CLI command overrides for supported agent backends."""

    claude: str | None = None
    codex: str | None = None


@dataclass
class DefaultsConfig:
    """Default values applied when spawn_workers fields are omitted."""

    agent_type: AgentType = "claude"
    skip_permissions: bool = False
    use_worktree: bool = True
    layout: LayoutMode = "auto"


@dataclass
class TerminalConfig:
    """Terminal backend configuration."""

    backend: TerminalBackend | None = None  # None = auto-detect


@dataclass
class EventsConfig:
    """Event log rotation configuration."""

    max_size_mb: int = 1
    recent_hours: int = 24


@dataclass
class IssueTrackerConfig:
    """Issue tracker configuration overrides."""

    override: IssueTrackerName | None = None


@dataclass
class ClaudeTeamConfig:
    """Top-level configuration container for claude-team."""

    version: int = CONFIG_VERSION
    commands: CommandsConfig = field(default_factory=CommandsConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    issue_tracker: IssueTrackerConfig = field(default_factory=IssueTrackerConfig)


def default_config() -> ClaudeTeamConfig:
    """Return a new config instance with default values."""

    return ClaudeTeamConfig()


def load_config(config_path: Path | None = None) -> ClaudeTeamConfig:
    """Load config from disk, creating defaults if missing."""

    path = _resolve_config_path(config_path)
    if not path.exists():
        return default_config()

    data = _read_json(path)
    return _parse_config(data)


def parse_config(data: dict) -> ClaudeTeamConfig:
    """Parse and validate a config dictionary."""

    return _parse_config(data)


def save_config(config: ClaudeTeamConfig, config_path: Path | None = None) -> Path:
    """Persist config to disk and return the path written."""

    path = _resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(config), indent=2, sort_keys=True)
    path.write_text(payload + "\n")
    return path


def _resolve_config_path(config_path: Path | None) -> Path:
    # Resolve the config path, using the default location if needed.
    return (config_path or CONFIG_PATH).expanduser()


def _read_json(path: Path) -> dict:
    # Read the file contents first so we can surface IO errors cleanly.
    try:
        raw = path.read_text()
    except OSError as exc:
        raise ConfigError(f"Unable to read config file: {path}") from exc

    # Decode JSON and enforce an object payload.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config file: {path}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Config file must contain a JSON object")

    return data


def _parse_config(data: dict) -> ClaudeTeamConfig:
    # Validate expected top-level keys before parsing sections.
    _validate_keys(
        data,
        {"version", "commands", "defaults", "terminal", "events", "issue_tracker"},
        "config",
    )
    version = _read_version(data.get("version"))
    commands = _parse_commands(data.get("commands"))
    defaults = _parse_defaults(data.get("defaults"))
    terminal = _parse_terminal(data.get("terminal"))
    events = _parse_events(data.get("events"))
    issue_tracker = _parse_issue_tracker(data.get("issue_tracker"))
    return ClaudeTeamConfig(
        version=version,
        commands=commands,
        defaults=defaults,
        terminal=terminal,
        events=events,
        issue_tracker=issue_tracker,
    )


def _read_version(value: object) -> int:
    # Allow missing versions for backward compatibility with early configs.
    if value is None:
        return CONFIG_VERSION
    if not isinstance(value, int):
        raise ConfigError("config.version must be an integer")
    if value != CONFIG_VERSION:
        raise ConfigError(
            f"Unsupported config version {value}; expected {CONFIG_VERSION}"
        )
    return value


def _parse_commands(value: object) -> CommandsConfig:
    # Parse CLI command overrides for each backend.
    data = _ensure_dict(value, "commands")
    _validate_keys(data, {"claude", "codex"}, "commands")
    return CommandsConfig(
        claude=_optional_str(data.get("claude"), "commands.claude"),
        codex=_optional_str(data.get("codex"), "commands.codex"),
    )


def _parse_defaults(value: object) -> DefaultsConfig:
    # Parse default spawn_workers fields with explicit validation.
    data = _ensure_dict(value, "defaults")
    _validate_keys(
        data,
        {"agent_type", "skip_permissions", "use_worktree", "layout"},
        "defaults",
    )
    return DefaultsConfig(
        agent_type=_optional_literal(
            data.get("agent_type"),
            {"claude", "codex"},
            "defaults.agent_type",
            DefaultsConfig.agent_type,
        ),
        skip_permissions=_optional_bool(
            data.get("skip_permissions"),
            "defaults.skip_permissions",
            DefaultsConfig.skip_permissions,
        ),
        use_worktree=_optional_bool(
            data.get("use_worktree"),
            "defaults.use_worktree",
            DefaultsConfig.use_worktree,
        ),
        layout=_optional_literal(
            data.get("layout"),
            {"auto", "new"},
            "defaults.layout",
            DefaultsConfig.layout,
        ),
    )


def _parse_terminal(value: object) -> TerminalConfig:
    # Parse terminal backend configuration.
    data = _ensure_dict(value, "terminal")
    _validate_keys(data, {"backend"}, "terminal")
    return TerminalConfig(
        backend=_optional_literal(
            data.get("backend"),
            {"iterm", "tmux"},
            "terminal.backend",
            None,
        ),
    )


def _parse_events(value: object) -> EventsConfig:
    # Parse event log rotation configuration.
    data = _ensure_dict(value, "events")
    _validate_keys(data, {"max_size_mb", "recent_hours"}, "events")
    return EventsConfig(
        max_size_mb=_optional_int(
            data.get("max_size_mb"),
            "events.max_size_mb",
            EventsConfig.max_size_mb,
            min_value=1,
        ),
        recent_hours=_optional_int(
            data.get("recent_hours"),
            "events.recent_hours",
            EventsConfig.recent_hours,
            min_value=0,
        ),
    )


def _parse_issue_tracker(value: object) -> IssueTrackerConfig:
    # Parse issue tracker overrides.
    data = _ensure_dict(value, "issue_tracker")
    _validate_keys(data, {"override"}, "issue_tracker")
    return IssueTrackerConfig(
        override=_optional_literal(
            data.get("override"),
            {"beads", "pebbles"},
            "issue_tracker.override",
            None,
        )
    )


def _ensure_dict(value: object, path: str) -> dict:
    # Ensure sections are JSON objects, defaulting to empty dicts.
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a JSON object")
    return value


def _validate_keys(data: dict, allowed: set[str], path: str) -> None:
    # Reject unexpected keys for a config section.
    unknown = set(data.keys()) - allowed
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ConfigError(f"Unknown keys in {path}: {joined}")


def _optional_str(value: object, path: str) -> str | None:
    # Validate optional string fields.
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{path} must be a string")
    if not value.strip():
        raise ConfigError(f"{path} cannot be empty")
    return value


def _optional_int(value: object, path: str, default: int, min_value: int = 1) -> int:
    # Validate optional integer fields.
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{path} must be an integer")
    if value < min_value:
        raise ConfigError(f"{path} must be at least {min_value}")
    return value


def _optional_bool(value: object, path: str, default: bool) -> bool:
    # Validate optional boolean fields.
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{path} must be a boolean")
    return value


def _optional_literal(
    value: object,
    allowed: set[str],
    path: str,
    default: str | None,
) -> str | None:
    # Validate optional string fields constrained to allowed values.
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(f"{path} must be a string")
    if value not in allowed:
        joined = ", ".join(sorted(allowed))
        raise ConfigError(f"{path} must be one of: {joined}")
    return value


__all__ = [
    "AgentType",
    "ClaudeTeamConfig",
    "CommandsConfig",
    "ConfigError",
    "DefaultsConfig",
    "EventsConfig",
    "IssueTrackerConfig",
    "LayoutMode",
    "TerminalBackend",
    "TerminalConfig",
    "IssueTrackerName",
    "CONFIG_DIR",
    "CONFIG_PATH",
    "CONFIG_VERSION",
    "default_config",
    "load_config",
    "parse_config",
    "save_config",
]
