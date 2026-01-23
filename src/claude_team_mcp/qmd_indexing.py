"""QMD indexing gating and prerequisites for claude-team."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("claude-team-mcp.indexing")

ENV_QMD_INDEXING = "CLAUDE_TEAM_QMD_INDEXING"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class QmdIndexingStatus:
    """Status details for QMD indexing enablement."""

    enabled: bool
    errors: tuple[str, ...] = ()


def _parse_env_flag(value: str | None, default: bool) -> bool:
    """Parse a boolean-ish environment flag."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return default


def _claude_projects_dir() -> Path:
    """Return the Claude projects directory."""
    return Path.home() / ".claude" / "projects"


def _codex_sessions_dir() -> Path:
    """Return the Codex sessions directory."""
    return Path.home() / ".codex" / "sessions"


def _index_root() -> Path:
    """Return the indexing root directory."""
    return Path.home() / ".claude-team" / "index"


def _run_qmd_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a qmd command and return the completed process."""
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )


def _check_prerequisites() -> list[str]:
    """Validate prerequisites for QMD indexing and return error messages."""
    errors: list[str] = []

    # Binary availability
    if shutil.which("qmd") is None:
        errors.append("qmd not found on PATH")

    # Required source directories
    claude_projects = _claude_projects_dir()
    if not claude_projects.exists():
        errors.append(f"Claude projects directory missing: {claude_projects}")

    codex_sessions = _codex_sessions_dir()
    if not codex_sessions.exists():
        errors.append(f"Codex sessions directory missing: {codex_sessions}")

    # Index root must be writable/creatable
    index_root = _index_root()
    try:
        index_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        errors.append(f"Cannot create index root {index_root}: {exc}")

    # If basic checks pass, validate qmd CLI health
    if not errors:
        result = _run_qmd_command(["qmd", "collection", "list"])
        if result.returncode != 0:
            stderr = result.stderr.strip() or "<no stderr>"
            errors.append(f"qmd collection list failed: {stderr}")

    return errors


def configure_qmd_indexing(server: Any, *, transport: str) -> QmdIndexingStatus:
    """Enable QMD indexing when running in HTTP mode and env allows it."""
    server.qmd_indexing_enabled = False
    server.qmd_indexing_errors = []

    # HTTP-only feature gate
    if transport != "streamable-http":
        logger.debug("QMD indexing disabled: transport '%s'", transport)
        return QmdIndexingStatus(enabled=False)

    # Explicit opt-in via env flag
    enabled = _parse_env_flag(os.environ.get(ENV_QMD_INDEXING), default=False)
    if not enabled:
        logger.info("QMD indexing disabled: %s not enabled", ENV_QMD_INDEXING)
        logger.info("smart_fork unavailable until indexing is enabled.")
        return QmdIndexingStatus(enabled=False)

    # Prerequisite checks: log and disable on any failure
    errors = _check_prerequisites()
    if errors:
        for error in errors:
            logger.error("QMD indexing prerequisite failed: %s", error)
        logger.info("smart_fork unavailable until indexing is healthy.")
        server.qmd_indexing_errors = errors
        return QmdIndexingStatus(enabled=False, errors=tuple(errors))

    server.qmd_indexing_enabled = True
    logger.info("QMD indexing prerequisites satisfied.")
    return QmdIndexingStatus(enabled=True)
