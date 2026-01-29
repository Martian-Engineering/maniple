"""
CLI helpers for claude-team configuration commands.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from collections.abc import Callable, Mapping

from . import config as config_module
from .config import ClaudeTeamConfig, ConfigError, parse_config

_ALLOWED_AGENT_TYPES = {"claude", "codex"}
_ALLOWED_LAYOUTS = {"auto", "new"}
_ALLOWED_TERMINAL_BACKENDS = {"iterm", "tmux"}
_ALLOWED_ISSUE_TRACKERS = {"beads", "pebbles"}


def init_config(
    *,
    force: bool = False,
    config_path: Path | None = None,
) -> Path:
    """Write the default config file to disk and return the path."""

    path = _resolve_config_path(config_path)
    if path.exists() and not force:
        raise ConfigError(f"Config file already exists: {path}")
    config = config_module.default_config()
    return config_module.save_config(config, path)


def load_effective_config_data(
    *,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict:
    """Load config data with environment overrides applied."""

    config = config_module.load_config(config_path)
    data = asdict(config)
    _apply_env_overrides(data, env or os.environ)
    return data


def render_config_json(
    *,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> str:
    """Render the effective config as formatted JSON."""

    data = load_effective_config_data(env=env, config_path=config_path)
    return json.dumps(data, indent=2, sort_keys=True)


def get_config_value(
    key: str,
    *,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> object:
    """Return a single config value by dotted path."""

    data = load_effective_config_data(env=env, config_path=config_path)
    return _get_nested_value(data, key)


def set_config_value(
    key: str,
    raw_value: str,
    *,
    config_path: Path | None = None,
) -> ClaudeTeamConfig:
    """Set a config value by dotted path, validate, and persist."""

    config = config_module.load_config(config_path)
    data = asdict(config)
    parsed_value = _parse_cli_value(key, raw_value)
    _set_nested_value(data, key, parsed_value)
    updated = parse_config(data)
    config_module.save_config(updated, _resolve_config_path(config_path))
    return updated


def format_value_json(value: object) -> str:
    """Format a single config value as JSON."""

    return json.dumps(value)


def _resolve_config_path(config_path: Path | None) -> Path:
    # Resolve the config path, defaulting to ~/.claude-team/config.json.
    return (config_path or config_module.CONFIG_PATH).expanduser()


def _apply_env_overrides(data: dict, env: Mapping[str, str]) -> None:
    # Apply env overrides using the same precedence logic as runtime helpers.
    command_override = env.get("CLAUDE_TEAM_COMMAND")
    if command_override:
        data["commands"]["claude"] = command_override

    codex_override = env.get("CLAUDE_TEAM_CODEX_COMMAND")
    if codex_override:
        data["commands"]["codex"] = codex_override

    # Terminal backend is a direct override (mirrors select_backend_id).
    backend_override = env.get("CLAUDE_TEAM_TERMINAL_BACKEND")
    if backend_override:
        data["terminal"]["backend"] = backend_override.strip().lower()

    # Issue tracker override mirrors detect_issue_tracker validation.
    tracker_override = env.get("CLAUDE_TEAM_ISSUE_TRACKER")
    if tracker_override:
        normalized = tracker_override.strip().lower()
        if normalized in _ALLOWED_ISSUE_TRACKERS:
            data["issue_tracker"]["override"] = normalized

    # Events overrides use integer parsing with graceful fallback.
    max_size_override = env.get("CLAUDE_TEAM_EVENTS_MAX_SIZE_MB")
    if max_size_override:
        parsed = _parse_int_override(max_size_override)
        if parsed is not None:
            data["events"]["max_size_mb"] = parsed

    recent_hours_override = env.get("CLAUDE_TEAM_EVENTS_RECENT_HOURS")
    if recent_hours_override:
        parsed = _parse_int_override(recent_hours_override)
        if parsed is not None:
            data["events"]["recent_hours"] = parsed


def _parse_int_override(raw_value: str) -> int | None:
    # Parse env overrides as integers; invalid values are ignored.
    try:
        return int(raw_value)
    except ValueError:
        return None


def _parse_cli_value(key: str, raw_value: str) -> object:
    # Parse CLI values according to the config schema.
    parser = _FIELD_PARSERS.get(key)
    if parser is None:
        raise ConfigError(f"Unknown config key: {key}")
    return parser(raw_value, key)


def _parse_optional_string(raw_value: str, field: str) -> str | None:
    # Parse optional string fields (allows null).
    if _is_null(raw_value):
        return None
    if not raw_value.strip():
        raise ConfigError(f"{field} cannot be empty")
    return raw_value


def _parse_bool(raw_value: str, field: str) -> bool:
    # Parse boolean values in JSON-compatible form.
    normalized = raw_value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigError(f"{field} must be a boolean")


def _parse_int(raw_value: str, field: str) -> int:
    # Parse integer values with minimum validation.
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise ConfigError(f"{field} must be an integer") from exc
    if value < 1:
        raise ConfigError(f"{field} must be at least 1")
    return value


def _parse_literal(raw_value: str, field: str, allowed: set[str]) -> str:
    # Parse literal string values constrained to allowed sets.
    value = raw_value.strip()
    if value not in allowed:
        joined = ", ".join(sorted(allowed))
        raise ConfigError(f"{field} must be one of: {joined}")
    return value


def _parse_optional_literal(
    raw_value: str,
    field: str,
    allowed: set[str],
) -> str | None:
    # Parse nullable literal values constrained to allowed sets.
    if _is_null(raw_value):
        return None
    return _parse_literal(raw_value, field, allowed)


def _is_null(raw_value: str) -> bool:
    # Treat "null" as a request to clear optional fields.
    return raw_value.strip().lower() == "null"


def _get_nested_value(data: dict, key: str) -> object:
    # Retrieve values by dotted path, validating against known keys.
    if key not in _GET_KEYS:
        raise ConfigError(f"Unknown config key: {key}")
    parts = key.split(".")
    current: object = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(f"Unknown config key: {key}")
        current = current[part]
    return current


def _set_nested_value(data: dict, key: str, value: object) -> None:
    # Assign values by dotted path, ensuring the key exists.
    parts = key.split(".")
    current: dict = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            raise ConfigError(f"Unknown config key: {key}")
        current = current[part]
    leaf = parts[-1]
    if leaf not in current:
        raise ConfigError(f"Unknown config key: {key}")
    current[leaf] = value


_FIELD_PARSERS: dict[str, Callable[[str, str], object]] = {
    "commands.claude": _parse_optional_string,
    "commands.codex": _parse_optional_string,
    "defaults.agent_type": lambda value, field: _parse_literal(
        value,
        field,
        _ALLOWED_AGENT_TYPES,
    ),
    "defaults.skip_permissions": _parse_bool,
    "defaults.use_worktree": _parse_bool,
    "defaults.layout": lambda value, field: _parse_literal(
        value,
        field,
        _ALLOWED_LAYOUTS,
    ),
    "terminal.backend": lambda value, field: _parse_optional_literal(
        value,
        field,
        _ALLOWED_TERMINAL_BACKENDS,
    ),
    "events.max_size_mb": _parse_int,
    "events.recent_hours": _parse_int,
    "issue_tracker.override": lambda value, field: _parse_optional_literal(
        value,
        field,
        _ALLOWED_ISSUE_TRACKERS,
    ),
}

_GET_KEYS = set(_FIELD_PARSERS.keys()) | {"version"}
