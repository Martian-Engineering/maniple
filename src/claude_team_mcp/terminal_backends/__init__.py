"""Terminal backend implementations and interfaces."""

from __future__ import annotations

import os
import shutil
from typing import Mapping

from .base import TerminalBackend, TerminalSession
from .iterm import ItermBackend, MAX_PANES_PER_TAB
from .tmux import TmuxBackend


def _ensure_tmux_available() -> None:
    """Ensure tmux is installed before using the tmux backend."""
    if shutil.which("tmux") is None:
        raise RuntimeError(
            "tmux backend selected but tmux is not installed. "
            "Install tmux or set CLAUDE_TEAM_TERMINAL_BACKEND=iterm."
        )


def select_backend_id(env: Mapping[str, str] | None = None) -> str:
    """Select a terminal backend id based on environment configuration."""
    environ = env or os.environ
    configured = environ.get("CLAUDE_TEAM_TERMINAL_BACKEND")
    if configured:
        backend_id = configured.strip().lower()
    elif environ.get("TMUX"):
        backend_id = "tmux"
    else:
        backend_id = "iterm"

    if backend_id == "tmux":
        _ensure_tmux_available()

    return backend_id


__all__ = [
    "TerminalBackend",
    "TerminalSession",
    "ItermBackend",
    "TmuxBackend",
    "MAX_PANES_PER_TAB",
    "select_backend_id",
]
