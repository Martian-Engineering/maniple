"""
Environment variable helpers.

This module provides small helpers for reading `MANIPLE_*` env vars while
supporting `CLAUDE_TEAM_*` as a temporary fallback during migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import os
import sys


@lru_cache(maxsize=None)
def _warn_deprecated_env_var(old_name: str, new_name: str) -> None:
    """Emit a one-time warning when a deprecated env var is used."""
    print(
        f"Warning: environment variable {old_name} is deprecated; use {new_name}.",
        file=sys.stderr,
    )


def get_env_with_fallback(
    new_name: str,
    old_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """
    Return an env var value, preferring `new_name` and falling back to `old_name`.

    When `old_name` is used, a one-time deprecation warning is emitted to stderr.

    Args:
        new_name: The canonical env var name (preferred).
        old_name: The deprecated env var name (fallback).
        env: Optional mapping to read from (defaults to os.environ).

    Returns:
        The resolved value, or None if neither env var is set (or is empty).
    """
    environ = os.environ if env is None else env

    value = environ.get(new_name)
    if value:
        return value

    value = environ.get(old_name)
    if value:
        _warn_deprecated_env_var(old_name, new_name)
        return value

    return None


def get_int_env_with_fallback(
    new_name: str,
    old_name: str,
    *,
    default: int,
    env: Mapping[str, str] | None = None,
) -> int:
    """
    Return an integer env var, preferring `new_name` and falling back to `old_name`.

    Invalid (non-integer) values are ignored and `default` is returned.
    """
    raw = get_env_with_fallback(new_name, old_name, env=env)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default

