"""Terminal backend implementations and interfaces."""

from __future__ import annotations

import logging
import os
from typing import Mapping

from ..config import ClaudeTeamConfig, ConfigError, load_config
from .base import TerminalBackend, TerminalSession
from .iterm import ItermBackend, MAX_PANES_PER_TAB
from .tmux import TmuxBackend
from ..utils.env_vars import get_env_with_fallback

logger = logging.getLogger("claude-team-mcp")


def select_backend_id(
    env: Mapping[str, str] | None = None,
    config: ClaudeTeamConfig | None = None,
) -> str:
    """Select a terminal backend id based on environment and config."""
    environ = os.environ if env is None else env
    configured = get_env_with_fallback(
        "MANIPLE_TERMINAL_BACKEND",
        "CLAUDE_TEAM_TERMINAL_BACKEND",
        env=environ,
    )
    if configured:
        return configured.strip().lower()
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
        return configured.strip().lower()
    if environ.get("TMUX"):
        return "tmux"
    return "iterm"


__all__ = [
    "TerminalBackend",
    "TerminalSession",
    "ItermBackend",
    "TmuxBackend",
    "MAX_PANES_PER_TAB",
    "select_backend_id",
]
