"""Terminal backend implementations and interfaces."""

from __future__ import annotations

from .base import TerminalBackend, TerminalSession
from .tmux import TmuxBackend

# MAX_PANES_PER_TAB is used by spawn_workers for layout decisions.
MAX_PANES_PER_TAB = 4


__all__ = [
    "TerminalBackend",
    "TerminalSession",
    "TmuxBackend",
    "MAX_PANES_PER_TAB",
]
