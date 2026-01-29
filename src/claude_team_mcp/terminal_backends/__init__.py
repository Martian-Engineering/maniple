"""Terminal backend implementations and interfaces."""

from __future__ import annotations

import os
from typing import Mapping

from .base import TerminalBackend, TerminalSession
from .iterm import ItermBackend, MAX_PANES_PER_TAB
from .tmux import TmuxBackend


def select_backend_id(env: Mapping[str, str] | None = None) -> str:
    """Select a terminal backend id based on environment configuration."""
    environ = env or os.environ
    configured = environ.get("CLAUDE_TEAM_TERMINAL_BACKEND")
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
