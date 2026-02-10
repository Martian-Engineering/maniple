"""Terminal backend implementations and interfaces."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping

from ..config import ClaudeTeamConfig, ConfigError, load_config
from .base import TerminalBackend, TerminalSession
from .iterm import ItermBackend, MAX_PANES_PER_TAB
from .tmux import TmuxBackend
from ..utils.env_vars import get_env_with_fallback

logger = logging.getLogger("maniple")


@dataclass(frozen=True)
class BackendSelection:
    """Represents the chosen terminal backend and whether it was explicitly configured."""

    backend_id: str
    explicit: bool


def select_backend(
    env: Mapping[str, str] | None = None,
    config: ClaudeTeamConfig | None = None,
) -> BackendSelection:
    """Select a terminal backend based on environment and config."""
    environ = os.environ if env is None else env
    configured = get_env_with_fallback(
        "MANIPLE_TERMINAL_BACKEND",
        "CLAUDE_TEAM_TERMINAL_BACKEND",
        env=environ,
    )
    if configured:
        return BackendSelection(configured.strip().lower(), True)
    if config is None:
        try:
            config = load_config()
        except ConfigError as exc:
            logger.warning(
                "Invalid config file; ignoring terminal backend override: %s", exc
            )
            config = None
    configured = config.terminal.backend if config else None
    if configured:
        return BackendSelection(configured.strip().lower(), True)
    if environ.get("TMUX"):
        return BackendSelection("tmux", False)
    return BackendSelection("iterm", False)


def select_backend_id(
    env: Mapping[str, str] | None = None,
    config: ClaudeTeamConfig | None = None,
) -> str:
    """Select a terminal backend id based on environment and config."""
    return select_backend(env=env, config=config).backend_id


__all__ = [
    "TerminalBackend",
    "TerminalSession",
    "ItermBackend",
    "TmuxBackend",
    "MAX_PANES_PER_TAB",
    "BackendSelection",
    "select_backend",
    "select_backend_id",
]
